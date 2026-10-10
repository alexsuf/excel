import json
import sys
import time
import pandas as pd
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, asdict
from pathlib import Path


def _dict_debug(msg: str):
    ts = time.strftime('%H:%M:%S')
    line = f"[dict][{ts}] {msg}"
    sys.stderr.write(line + "\n")
    sys.stderr.flush()
    try:
        from app.core.config import settings
        log_path = Path(settings.output_dir) / "llm.log"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with open(log_path, "a", encoding="utf-8") as lf:
            lf.write(line + "\n")
            lf.flush()
            import os
            os.fsync(lf.fileno())
    except Exception:
        pass


@dataclass
class FieldMapping:
    field_name: str
    description: str
    entity_type: str
    extraction_hint: str
    data_type: str = "string"
    required: bool = False
    default_value: Any = None
    validation_rules: Dict[str, Any] = None
    examples: List[str] = None
    
    def __post_init__(self):
        if self.validation_rules is None:
            self.validation_rules = {}
        if self.examples is None:
            self.examples = []


class DictionaryManager:
    def __init__(self, dictionary_path: Optional[str] = None):
        self.mappings: Dict[str, FieldMapping] = {}
        self.dictionary_path = dictionary_path
        if dictionary_path and Path(dictionary_path).exists():
            _dict_debug(f"INIT: dictionary exists at {dictionary_path}")
            self.load(dictionary_path)
        else:
            _dict_debug("INIT: no dictionary path or file does not exist")
    
    def load(self, path: str):
        _dict_debug(f"LOAD START: {path}")
        self.dictionary_path = path
        ext = Path(path).suffix.lower()
        _dict_debug(f"LOAD: format={ext}")
        
        if ext == '.json':
            self._load_json(path)
        elif ext in ['.xlsx', '.xls', '.csv']:
            self._load_excel(path)
        else:
            raise ValueError(f"Unsupported dictionary format: {ext}")
        _dict_debug(f"LOAD DONE: {len(self.mappings)} mappings loaded")
    
    def _load_json(self, path: str):
        _dict_debug(f"_load_json START: {path}")
        t0 = time.time()
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        _dict_debug(f"_load_json: file read in {time.time()-t0:.3f}s, type={type(data).__name__}")
        
        if isinstance(data, dict):
            for key, value in data.items():
                if isinstance(value, dict):
                    self.mappings[key] = FieldMapping(
                        field_name=key,
                        description=value.get('description', ''),
                        entity_type=value.get('entity_type', ''),
                        extraction_hint=value.get('extraction_hint', ''),
                        data_type=value.get('data_type', 'string'),
                        required=value.get('required', False),
                        default_value=value.get('default_value'),
                        validation_rules=value.get('validation_rules', {}),
                        examples=value.get('examples', [])
                    )
                elif isinstance(value, str):
                    self.mappings[key] = FieldMapping(
                        field_name=key,
                        description=value,
                        entity_type='',
                        extraction_hint='',
                        data_type='string'
                    )
        elif isinstance(data, list):
            for item in data:
                if isinstance(item, dict) and 'field_name' in item:
                    self.mappings[item['field_name']] = FieldMapping(**item)
        _dict_debug(f"_load_json DONE in {time.time()-t0:.3f}s, mappings={len(self.mappings)}")
    
    def _load_excel(self, path: str):
        _dict_debug(f"_load_excel START: {path}")
        t0 = time.time()
        if path.endswith('.csv'):
            _dict_debug("_load_excel: reading CSV...")
            df = pd.read_csv(path)
        else:
            _dict_debug("_load_excel: reading Excel...")
            df = pd.read_excel(path)
        _dict_debug(f"_load_excel: read in {time.time()-t0:.3f}s, rows={len(df)}, cols={list(df.columns)}")
        
        required_cols = ['field_name', 'description', 'entity_type', 'extraction_hint']
        for col in required_cols:
            if col not in df.columns:
                raise ValueError(f"Required column '{col}' not found in dictionary")
        
        t1 = time.time()
        for idx, row in df.iterrows():
            if idx < 3 or idx % 100 == 0:
                _dict_debug(f"  Processing row {idx}: {row.get('field_name', '?')}")
            mapping = FieldMapping(
                field_name=str(row['field_name']),
                description=str(row['description']),
                entity_type=str(row['entity_type']),
                extraction_hint=str(row['extraction_hint']),
                data_type=str(row.get('data_type', 'string')),
                required=bool(row.get('required', False)),
                default_value=row.get('default_value'),
                validation_rules=json.loads(row['validation_rules']) if pd.notna(row.get('validation_rules')) else {},
                examples=json.loads(row['examples']) if pd.notna(row.get('examples')) else []
            )
            self.mappings[mapping.field_name] = mapping
        _dict_debug(f"_load_excel: processed {len(df)} rows in {time.time()-t1:.3f}s, total mappings={len(self.mappings)}")
    
    def save(self, path: str):
        ext = Path(path).suffix.lower()
        
        if ext == '.json':
            self._save_json(path)
        elif ext in ['.xlsx', '.xls', '.csv']:
            self._save_excel(path)
        else:
            raise ValueError(f"Unsupported dictionary format: {ext}")
    
    def _save_json(self, path: str):
        data = {name: asdict(mapping) for name, mapping in self.mappings.items()}
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    
    def _save_excel(self, path: str):
        rows = []
        for mapping in self.mappings.values():
            row = asdict(mapping)
            row['validation_rules'] = json.dumps(row['validation_rules'], ensure_ascii=False)
            row['examples'] = json.dumps(row['examples'], ensure_ascii=False)
            rows.append(row)
        
        df = pd.DataFrame(rows)
        if path.endswith('.csv'):
            df.to_csv(path, index=False, encoding='utf-8')
        else:
            df.to_excel(path, index=False)
    
    def get_mapping(self, field_name: str) -> Optional[FieldMapping]:
        return self.mappings.get(field_name)
    
    def get_all_mappings(self) -> Dict[str, FieldMapping]:
        return self.mappings
    
    def add_mapping(self, mapping: FieldMapping):
        self.mappings[mapping.field_name] = mapping
    
    def remove_mapping(self, field_name: str):
        if field_name in self.mappings:
            del self.mappings[field_name]
    
    def build_extraction_prompt(self, template_fields: List[str], template_analyzer=None) -> str:
        _dict_debug(f"build_extraction_prompt START, fields={len(template_fields)}")
        t0 = time.time()
        labels = template_analyzer.get_field_labels() if template_analyzer else {}
        lines = [
            "You are an expert data extraction assistant. Extract the following fields from the provided documents.",
            "Return ONLY a valid JSON object with the extracted fields.",
            "",
            "Fields to extract:"
        ]
        
        for field_name in template_fields:
            mapping = self.mappings.get(field_name)
            nr = template_analyzer.get_named_ranges().get(field_name) if template_analyzer else None
            _dict_debug(f"  Building prompt for field '{field_name}': mapping={'yes' if mapping else 'no'}, nr={'yes' if nr else 'no'}")
            
            if mapping:
                lines.append(f"- {field_name}: {mapping.description}")
                if field_name in labels:
                    lines.append(f"  Template cell label: {labels[field_name]}")
                lines.append(f"  Entity type: {mapping.entity_type}")
                lines.append(f"  Hint: {mapping.extraction_hint}")
                lines.append(f"  Data type: {mapping.data_type}")
                if mapping.examples:
                    example_strs = []
                    for ex in mapping.examples:
                        if isinstance(ex, str):
                            example_strs.append(ex)
                        elif isinstance(ex, dict):
                            example_strs.append(str(ex))
                        else:
                            example_strs.append(str(ex))
                    lines.append(f"  Examples: {', '.join(example_strs)}")
                if mapping.required:
                    lines.append("  REQUIRED: true")
                if mapping.validation_rules:
                    rules_desc = ", ".join([f"{k}={v}" for k, v in mapping.validation_rules.items()])
                    lines.append(f"  Validation rules: {rules_desc}")
            elif nr and nr.is_table:
                lines.append(f"- {field_name}: Table with columns: {', '.join(nr.table_headers)}")
                lines.append(f"  Template cell label: {labels.get(field_name, 'table')}")
                lines.append(f"  Data type: table")
                lines.append(f"  Columns: {', '.join(nr.table_headers)}")
                lines.append("  REQUIRED: false")
            else:
                lines.append(f"- {field_name}: No description available")
                if nr and nr.is_table:
                    lines.append(f"  Data type: table")
                    lines.append(f"  Columns: {', '.join(nr.table_headers)}")
        
        lines.extend([
            "",
            "Rules:",
            "1. Return strictly typed JSON matching the field types",
            "2. For dates, use ISO format (YYYY-MM-DD)",
            "3. For numbers, return numeric values, not strings",
            "4. For tables, return array of objects with column names as keys",
            "5. If a field is not found, omit it or set to null",
            "6. Do not include any explanatory text, only the JSON",
            "7. For table fields, each row must be an object with all column keys",
            "8. Numeric values should not have currency symbols or thousand separators",
            "9. Boolean values should be true/false, not yes/no"
        ])
        
        result = "\n".join(lines)
        _dict_debug(f"build_extraction_prompt DONE in {time.time()-t0:.3f}s, prompt={len(result)} chars")
        return result
    
    def validate_field(self, field_name: str, value: Any) -> tuple[bool, List[str]]:
        mapping = self.mappings.get(field_name)
        if not mapping:
            return True, []
        
        errors = []
        
        if mapping.required and (value is None or value == ""):
            errors.append(f"Field '{field_name}' is required but missing")
            return False, errors
        
        if value is None:
            return True, []
        
        if mapping.data_type == "number":
            try:
                float(value)
            except (ValueError, TypeError):
                errors.append(f"Field '{field_name}' must be a number")
        
        elif mapping.data_type == "integer":
            try:
                int(value)
            except (ValueError, TypeError):
                errors.append(f"Field '{field_name}' must be an integer")
        
        elif mapping.data_type == "date":
            if isinstance(value, str):
                import re
                if not re.match(r'^\d{4}-\d{2}-\d{2}$', value):
                    errors.append(f"Field '{field_name}' must be in YYYY-MM-DD format")
        
        elif mapping.data_type == "boolean":
            if not isinstance(value, bool):
                errors.append(f"Field '{field_name}' must be a boolean")
        
        for rule, rule_value in mapping.validation_rules.items():
            if rule == "min_length" and isinstance(value, str):
                if len(value) < rule_value:
                    errors.append(f"Field '{field_name}' must be at least {rule_value} characters")
            elif rule == "max_length" and isinstance(value, str):
                if len(value) > rule_value:
                    errors.append(f"Field '{field_name}' must be at most {rule_value} characters")
            elif rule == "pattern" and isinstance(value, str):
                import re
                if not re.match(rule_value, value):
                    errors.append(f"Field '{field_name}' does not match pattern {rule_value}")
        
        return len(errors) == 0, errors
    
    def to_dict(self) -> Dict[str, Any]:
        return {name: asdict(mapping) for name, mapping in self.mappings.items()}
