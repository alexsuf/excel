from typing import Dict, List, Any, Optional
from dataclasses import dataclass, field
from pathlib import Path
import json
import sys
import uuid
import time
from datetime import datetime

import jsonschema

from app.core.template_analyzer import TemplateAnalyzer, analyze_template
from app.core.dictionary import DictionaryManager, FieldMapping
from app.core.llm_client import LLMClient, get_llm_client
from app.core.validator import DataValidator, ExtractionResult
from app.core.excel_writer import ExcelWriter
from app.core.config import settings


@dataclass
class PipelineState:
    session_id: str
    template_path: Optional[str] = None
    dictionary_path: Optional[str] = None
    document_paths: List[str] = field(default_factory=list)
    template_analyzer: Optional[TemplateAnalyzer] = None
    dictionary_manager: Optional[DictionaryManager] = None
    extracted_data: Optional[Dict[str, Any]] = None
    validation_result: Optional[ExtractionResult] = None
    output_path: Optional[str] = None
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now().isoformat())
    status: str = "initialized"
    errors: List[str] = field(default_factory=list)


class PipelineOrchestrator:
    def __init__(self):
        self.sessions: Dict[str, PipelineState] = {}
        self.llm_client = get_llm_client()

    def _log(self, session_id: str, message: str):
        log_path = Path(settings.log_dir) / f"{session_id}.log"
        ts = datetime.now().strftime("%H:%M:%S")
        line = f"[{ts}] {message}"
        print(line, flush=True)
        try:
            log_path.parent.mkdir(parents=True, exist_ok=True)
            with open(log_path, "a", encoding="utf-8") as f:
                f.write(line + "\n")
                f.flush()
                import os
                os.fsync(f.fileno())
        except Exception:
            pass

    def create_session(self) -> str:
        session_id = str(uuid.uuid4())[:8]
        self.sessions[session_id] = PipelineState(session_id=session_id)
        self._log(session_id, f"Session created")
        return session_id

    def get_session(self, session_id: str) -> Optional[PipelineState]:
        return self.sessions.get(session_id)

    def load_template(self, session_id: str, template_path: str) -> Dict[str, Any]:
        state = self.get_session(session_id)
        if not state:
            raise ValueError("Session not found")
        state.template_path = template_path
        state.template_analyzer = analyze_template(template_path)
        state.updated_at = datetime.now().isoformat()
        self._log(session_id, f"Template loaded: {template_path}")
        return {
            "success": True,
            "named_ranges": state.template_analyzer.to_dict(),
            "schema": state.template_analyzer.get_field_schema()
        }

    def load_dictionary(self, session_id: str, dictionary_path: str) -> Dict[str, Any]:
        state = self.get_session(session_id)
        if not state:
            raise ValueError("Session not found")
        state.dictionary_path = dictionary_path
        state.dictionary_manager = DictionaryManager(dictionary_path)
        state.updated_at = datetime.now().isoformat()
        self._log(session_id, f"Dictionary loaded: {dictionary_path}")
        return {
            "success": True,
            "mappings": state.dictionary_manager.to_dict()
        }

    def add_documents(self, session_id: str, document_paths: List[str]) -> Dict[str, Any]:
        state = self.get_session(session_id)
        if not state:
            raise ValueError("Session not found")
        state.document_paths = document_paths
        state.updated_at = datetime.now().isoformat()
        self._log(session_id, f"Documents uploaded: {len(document_paths)} files")
        return {"success": True, "document_count": len(document_paths)}

    def extract_data(self, session_id: str) -> Dict[str, Any]:
        print(" ------------- extract data -------------", flush=True)
        state = self.get_session(session_id)
        if not state:
            raise ValueError("Session not found")
        if not state.template_analyzer:
            raise ValueError("Template not loaded")
        if not state.dictionary_manager:
            raise ValueError("Dictionary not loaded")
        if not state.document_paths:
            raise ValueError("No documents provided")
        state.status = "extracting"
        state.updated_at = datetime.now().isoformat()

        llm_log = self.llm_client.log
        import os as _os
        _debug_file = Path(settings.output_dir) / "pipeline_debug.log"
        _debug_file.parent.mkdir(parents=True, exist_ok=True)
        _abs_debug = str(_debug_file.resolve())
        def _write_debug(msg: str):
            ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")
            line = f"[{ts}] {msg}\n"
            llm_log.info(msg)
            self._log(session_id, msg)
            sys.stderr.write(f"[PD][{ts}] {msg}\n")
            sys.stderr.flush()
            try:
                with open(_debug_file, "a", encoding="utf-8") as lf:
                    lf.write(line)
                    lf.flush()
                    _os.fsync(lf.fileno())
            except Exception:
                pass

        _write_debug("=" * 70)
        _write_debug("EXTRACT DATA STARTED")
        _write_debug(f"session_id={session_id}")
        _write_debug(f"document_paths={state.document_paths}")
        _write_debug(f"template_loaded={state.template_analyzer is not None}")
        _write_debug(f"dictionary_loaded={state.dictionary_manager is not None}")
        _write_debug(f"debug_log={_abs_debug}")
        t0 = time.time()

        # --- Input validation ---
        _write_debug("Check: session exists")
        t_v = time.time()
        state = self.get_session(session_id)
        if not state:
            _write_debug("FAIL: Session not found")
            raise ValueError("Session not found")
        _write_debug(f"OK: session found ({time.time()-t_v:.3f}s)")

        _write_debug("Check: template_analyzer")
        t_v = time.time()
        if not state.template_analyzer:
            _write_debug("FAIL: Template not loaded")
            raise ValueError("Template not loaded")
        _write_debug(f"OK: template_analyzer ready ({time.time()-t_v:.3f}s)")

        _write_debug("Check: dictionary_manager")
        t_v = time.time()
        if not state.dictionary_manager:
            _write_debug("FAIL: Dictionary not loaded")
            raise ValueError("Dictionary not loaded")
        _write_debug(f"OK: dictionary_manager ready ({time.time()-t_v:.3f}s)")

        _write_debug("Check: document_paths")
        t_v = time.time()
        if not state.document_paths:
            _write_debug("FAIL: No documents provided")
            raise ValueError("No documents provided")
        _write_debug(f"OK: {len(state.document_paths)} documents ({time.time()-t_v:.3f}s)")

        state.status = "extracting"
        state.updated_at = datetime.now().isoformat()

        # --- Step 1: Build schema ---
        _write_debug("Step 1: Building schema from template...")
        t1 = time.time()
        try:
            named_ranges = list(state.template_analyzer.get_named_ranges().keys())
            _write_debug(f"  named_ranges: {named_ranges}")
            _write_debug("  Calling get_field_schema...")
            schema = state.template_analyzer.get_field_schema(state.dictionary_manager)
            _write_debug(f"  get_field_schema DONE: {len(schema.get('properties', {}))} fields in {time.time()-t1:.2f}s")
            for name, prop in schema.get("properties", {}).items():
                _write_debug(f"  field[{name}]: type={prop.get('type', '?')}, desc={str(prop.get('description',''))[:80]}")
            schema_required = schema.get("required", [])
            _write_debug(f"  required fields: {schema_required}")
        except Exception as e:
            _write_debug(f"  FAIL: schema build error: {e}")
            raise

        # --- Step 2: Build prompt ---
        _write_debug("Step 2: Building extraction prompt...")
        t2 = time.time()
        try:
            prompt = state.dictionary_manager.build_extraction_prompt(
                list(state.template_analyzer.get_named_ranges().keys()),
                state.template_analyzer
            )
            _write_debug(f"  Prompt built: {len(prompt)} chars in {time.time()-t2:.2f}s")
            _write_debug(f"  Prompt preview: {prompt[:500]}")
        except Exception as e:
            _write_debug(f"  FAIL: prompt build error: {e}")
            raise

        # --- Step 3: Prepare documents ---
        _write_debug(f"Step 3: Preparing {len(state.document_paths)} documents...")
        t3 = time.time()
        for i, fp in enumerate(state.document_paths):
            _write_debug(f"  doc[{i}]: {fp}")
            t_doc = time.time()
            from pathlib import Path as _P
            _p = _P(fp)
            _write_debug(f"    exists={_p.exists()} size={_p.stat().st_size if _p.exists() else 0}")
            try:
                import mimetypes as _mt
                _mime, _ = _mt.guess_type(str(_p))
                _write_debug(f"    mime={_mime}")
            except Exception:
                pass
            _write_debug(f"    prepared in {time.time()-t_doc:.3f}s")
        _write_debug(f"Documents prepared: {time.time()-t3:.2f}s total")

        # --- Step 4: LLM extraction ---
        _write_debug(f"Step 4: Calling LLM (timeout={settings.llm_timeout}s)...")
        t4 = time.time()
        try:
            extracted = self.llm_client.extract_from_files(
                state.document_paths, prompt, schema
            )
            _write_debug(f"LLM DONE: {len(extracted)} fields in {time.time()-t4:.2f}s")
            for k, v in extracted.items():
                _write_debug(f"  [{k}]: {str(v)[:200]}")
        except Exception as e:
            _write_debug(f"LLM FAILED after {time.time()-t4:.2f}s: {e}")
            state.status = "error"
            state.errors.append(str(e))
            state.updated_at = datetime.now().isoformat()
            raise

        # --- Step 5: Validate ---
        _write_debug("Step 5: Validating with JSON schema...")
        t5 = time.time()
        try:
            js_errors = self._validate_with_jsonschema(extracted, schema)
            _write_debug(f"Validation done in {time.time()-t5:.2f}s, errors={len(js_errors)}")
            for e in js_errors:
                _write_debug(f"  schema warning: {e}")
        except Exception as e:
            _write_debug(f"Validation error: {e}")
            raise

        if js_errors:
            state.status = "extracted"
            state.extracted_data = extracted
            state.updated_at = datetime.now().isoformat()
            _write_debug("Result: extracted with schema warnings")
            _write_debug(f"Total time: {time.time()-t0:.2f}s")
            _write_debug("=" * 70)
            return {
                "success": True,
                "extracted_data": extracted,
                "schema_warnings": js_errors
            }

        state.extracted_data = extracted
        state.status = "extracted"
        state.updated_at = datetime.now().isoformat()
        _write_debug("Step 6: Validation OK")
        _write_debug("=== Extraction complete ===")
        _write_debug(f"Total time: {time.time()-t0:.2f}s")
        _write_debug("=" * 70)
        return {"success": True, "extracted_data": extracted}

    def _validate_with_jsonschema(self, data: Dict[str, Any], schema: Dict[str, Any]) -> List[str]:
        warnings = []
        try:
            jsonschema.validate(instance=data, schema=schema)
        except jsonschema.ValidationError as e:
            warnings.append(f"JSON Schema: {e.message}")
        return warnings

    def validate_data(self, session_id: str) -> Dict[str, Any]:
        state = self.get_session(session_id)
        if not state:
            raise ValueError("Session not found")
        if not state.extracted_data:
            raise ValueError("No extracted data to validate")
        state.status = "validating"
        state.updated_at = datetime.now().isoformat()
        try:
            validator = DataValidator(state.template_analyzer, state.dictionary_manager)
            result = validator.validate(state.extracted_data)
            state.validation_result = result
            state.status = "validated"
            state.updated_at = datetime.now().isoformat()
            return {
                "success": True,
                "is_valid": result.is_valid,
                "fields": {k: {
                    "value": v.value, "data_type": v.data_type,
                    "is_valid": v.is_valid, "errors": v.errors, "warnings": v.warnings
                } for k, v in result.fields.items()},
                "tables": {k: {
                    "headers": v.headers,
                    "rows": [{"cells": r.cells, "is_valid": r.is_valid, "errors": r.errors} for r in v.rows],
                    "is_valid": v.is_valid, "errors": v.errors
                } for k, v in result.tables.items()},
                "errors": result.errors,
                "warnings": result.warnings
            }
        except Exception as e:
            state.status = "error"
            state.errors.append(f"Validation failed: {str(e)}")
            state.updated_at = datetime.now().isoformat()
            return {"success": False, "error": str(e)}

    def update_field(self, session_id: str, field_name: str, new_value: Any) -> Dict[str, Any]:
        state = self.get_session(session_id)
        if not state:
            raise ValueError("Session not found")
        if not state.validation_result:
            raise ValueError("No validation result to update")
        if field_name in state.validation_result.fields:
            field = state.validation_result.fields[field_name]
            field.value = new_value
            mapping = state.dictionary_manager.get_mapping(field_name)
            is_valid, errors = state.dictionary_manager.validate_field(field_name, new_value)
            field.is_valid = is_valid
            field.errors = errors
            if is_valid:
                v = DataValidator(state.template_analyzer, state.dictionary_manager)
                field = v._normalize_field(field, mapping)
            if state.extracted_data is not None:
                state.extracted_data[field_name] = field.value
            state.validation_result.is_valid = (
                all(f.is_valid for f in state.validation_result.fields.values()) and
                all(t.is_valid for t in state.validation_result.tables.values())
            )
            state.validation_result.errors = []
            for f in state.validation_result.fields.values():
                state.validation_result.errors.extend(f.errors)
            for t in state.validation_result.tables.values():
                state.validation_result.errors.extend(t.errors)
            state.updated_at = datetime.now().isoformat()
            return {"success": True, "field": {"value": field.value, "is_valid": field.is_valid, "errors": field.errors}}
        elif field_name in state.validation_result.tables:
            return {"success": False, "error": "Use update_table_row for table fields"}
        else:
            return {"success": False, "error": f"Field {field_name} not found"}

    def update_table_row(self, session_id: str, table_name: str, row_index: int, row_data: Dict[str, Any]) -> Dict[str, Any]:
        state = self.get_session(session_id)
        if not state:
            raise ValueError("Session not found")
        if not state.validation_result or table_name not in state.validation_result.tables:
            raise ValueError("Table not found")
        table = state.validation_result.tables[table_name]
        if row_index >= len(table.rows):
            raise ValueError("Row index out of bounds")
        row = table.rows[row_index]
        for header, value in row_data.items():
            if header in row.cells:
                row.cells[header] = value
        validator = DataValidator(state.template_analyzer, state.dictionary_manager)
        nr = state.template_analyzer.get_named_ranges()[table_name]
        for header in nr.table_headers:
            cell_value = row.cells.get(header)
            field_result = validator._validate_field(f"{table_name}.{header}", cell_value, nr, None)
            row.cells[header] = field_result.value
            if not field_result.is_valid:
                row.is_valid = False
                row.errors = field_result.errors
            else:
                row.errors = []
        table.is_valid = all(r.is_valid for r in table.rows)
        table.errors = []
        for r in table.rows:
            table.errors.extend(r.errors)
        if state.extracted_data is not None:
            table_data = state.extracted_data.get(table_name)
            if isinstance(table_data, list) and row_index < len(table_data):
                state.extracted_data[table_name][row_index] = row.cells
        state.validation_result.is_valid = (
            all(f.is_valid for f in state.validation_result.fields.values()) and
            all(t.is_valid for t in state.validation_result.tables.values())
        )
        state.updated_at = datetime.now().isoformat()
        return {"success": True, "row": {"cells": row.cells, "is_valid": row.is_valid, "errors": row.errors}}

    def generate_output(self, session_id: str, output_filename: Optional[str] = None) -> Dict[str, Any]:
        state = self.get_session(session_id)
        if not state:
            raise ValueError("Session not found")
        if not state.validation_result:
            raise ValueError("No validation result available")
        state.status = "generating"
        state.updated_at = datetime.now().isoformat()
        try:
            if not output_filename:
                output_filename = f"output_{session_id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
            output_path = Path(settings.output_dir) / output_filename
            output_path.parent.mkdir(parents=True, exist_ok=True)
            writer = ExcelWriter(state.template_path)
            writer.write_data(state.validation_result, str(output_path))
            state.output_path = str(output_path)
            state.status = "completed"
            state.updated_at = datetime.now().isoformat()
            return {
                "success": True,
                "output_path": str(output_path),
                "download_url": f"/api/download/{session_id}/{output_filename}"
            }
        except Exception as e:
            state.status = "error"
            state.errors.append(f"Generation failed: {str(e)}")
            state.updated_at = datetime.now().isoformat()
            return {"success": False, "error": str(e)}

    def get_session_status(self, session_id: str) -> Dict[str, Any]:
        state = self.get_session(session_id)
        if not state:
            return {"success": False, "error": "Session not found"}
        return {
            "success": True,
            "session_id": state.session_id,
            "status": state.status,
            "template_loaded": state.template_analyzer is not None,
            "dictionary_loaded": state.dictionary_manager is not None,
            "documents_count": len(state.document_paths),
            "extracted": state.extracted_data is not None,
            "validated": state.validation_result is not None,
            "output_ready": state.output_path is not None,
            "errors": state.errors,
            "created_at": state.created_at,
            "updated_at": state.updated_at
        }


pipeline = PipelineOrchestrator()