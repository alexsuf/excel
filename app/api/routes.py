from flask import Blueprint, request, jsonify, send_file, current_app
from werkzeug.utils import secure_filename
import os
import sys
import time
from pathlib import Path
import uuid

from app.core.pipeline import pipeline, PipelineOrchestrator
from app.core.config import settings
from app.core.excel_writer import ExcelWriter


api_bp = Blueprint('api', __name__)

ALLOWED_EXTENSIONS = {'.xlsx', '.xls', '.pdf', '.docx', '.txt', '.csv', '.json', '.md'}


def allowed_file(filename: str) -> bool:
    return Path(filename).suffix.lower() in ALLOWED_EXTENSIONS


def save_uploaded_file(file, subdir: str) -> str:
    original_filename = file.filename
    suffix = Path(original_filename).suffix.lower()
    base_name = secure_filename(original_filename)
    if not base_name or base_name == suffix.lstrip('.'):
        base_name = "file"
    unique_name = f"{uuid.uuid4().hex[:8]}_{base_name}{suffix}"
    save_dir = Path(settings.data_dir) / subdir
    save_dir.mkdir(parents=True, exist_ok=True)
    save_path = save_dir / unique_name
    file.save(str(save_path))
    return str(save_path)


@api_bp.route('/health', methods=['GET'])
def health_check():
    return jsonify({"status": "ok", "service": "excel-fill-api"})


@api_bp.route('/session', methods=['POST'])
def create_session():
    session_id = pipeline.create_session()
    return jsonify({"session_id": session_id})


@api_bp.route('/session/<session_id>', methods=['GET'])
def get_session_status(session_id):
    return jsonify(pipeline.get_session_status(session_id))


@api_bp.route('/session/<session_id>/logs', methods=['GET'])
def get_session_logs(session_id):
    state = pipeline.get_session(session_id)
    if not state:
        return jsonify({"success": False, "error": "Session not found"}), 404
    logs = []
    log_file = Path(settings.output_dir) / f"{session_id}.log"
    if log_file.exists():
        logs = log_file.read_text(encoding="utf-8").splitlines()
    return jsonify({"success": True, "logs": logs})


@api_bp.route('/session/<session_id>/template', methods=['POST'])
def upload_template(session_id):
    if 'file' not in request.files:
        return jsonify({"success": False, "error": "No file provided"}), 400
    
    file = request.files['file']
    if file.filename == '':
        return jsonify({"success": False, "error": "No file selected"}), 400
    
    if not allowed_file(file.filename):
        return jsonify({"success": False, "error": "File type not allowed"}), 400
    
    try:
        template_path = save_uploaded_file(file, 'templates')
        result = pipeline.load_template(session_id, template_path)
        return jsonify(result)
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@api_bp.route('/session/<session_id>/dictionary', methods=['POST'])
def upload_dictionary(session_id):
    if 'file' not in request.files:
        return jsonify({"success": False, "error": "No file provided"}), 400
    
    file = request.files['file']
    if file.filename == '':
        return jsonify({"success": False, "error": "No file selected"}), 400
    
    if not allowed_file(file.filename):
        return jsonify({"success": False, "error": "File type not allowed"}), 400
    
    try:
        dict_path = save_uploaded_file(file, 'dictionaries')
        result = pipeline.load_dictionary(session_id, dict_path)
        return jsonify(result)
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@api_bp.route('/session/<session_id>/documents', methods=['POST'])
def upload_documents(session_id):
    if 'files' not in request.files:
        return jsonify({"success": False, "error": "No files provided"}), 400
    
    files = request.files.getlist('files')
    if not files or all(f.filename == '' for f in files):
        return jsonify({"success": False, "error": "No files selected"}), 400
    
    document_paths = []
    for file in files:
        if file.filename and allowed_file(file.filename):
            doc_path = save_uploaded_file(file, 'input')
            document_paths.append(doc_path)
    
    if not document_paths:
        return jsonify({"success": False, "error": "No valid files uploaded"}), 400
    
    try:
        result = pipeline.add_documents(session_id, document_paths)
        return jsonify(result)
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@api_bp.route('/session/<session_id>/extract', methods=['POST'])
def extract_data(session_id):
    ts = time.strftime('%H:%M:%S')
    log_path = Path(settings.output_dir) / "api_debug.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    msg = f"[{ts}] API /extract called for session={session_id}\n"
    sys.stderr.write(msg)
    sys.stderr.flush()
    try:
        with open(log_path, "a", encoding="utf-8") as lf:
            lf.write(msg)
            lf.flush()
            os.fsync(lf.fileno())
    except Exception:
        pass
    try:
        result = pipeline.extract_data(session_id)
        return jsonify(result)
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@api_bp.route('/session/<session_id>/validate', methods=['POST'])
def validate_data(session_id):
    try:
        result = pipeline.validate_data(session_id)
        return jsonify(result)
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@api_bp.route('/session/<session_id>/validate-schema', methods=['POST'])
def validate_json_schema(session_id):
    state = pipeline.get_session(session_id)
    if not state:
        return jsonify({"success": False, "error": "Session not found"}), 404
    if not state.extracted_data:
        return jsonify({"success": False, "error": "No extracted data"}), 400
    try:
        import jsonschema as js
        schema = state.template_analyzer.get_field_schema(state.dictionary_manager)
        errors = []
        try:
            js.validate(instance=state.extracted_data, schema=schema)
        except js.ValidationError as e:
            errors.append(e.message)
        return jsonify({"success": True, "is_valid": len(errors) == 0, "errors": errors})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@api_bp.route('/session/<session_id>/field', methods=['PUT'])
def update_field(session_id):
    data = request.get_json()
    if not data or 'field_name' not in data or 'value' not in data:
        return jsonify({"success": False, "error": "field_name and value required"}), 400
    
    try:
        result = pipeline.update_field(session_id, data['field_name'], data['value'])
        return jsonify(result)
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@api_bp.route('/session/<session_id>/table/<table_name>/row/<int:row_index>', methods=['PUT'])
def update_table_row(session_id, table_name, row_index):
    data = request.get_json()
    if not data:
        return jsonify({"success": False, "error": "Row data required"}), 400
    
    try:
        result = pipeline.update_table_row(session_id, table_name, row_index, data)
        return jsonify(result)
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@api_bp.route('/session/<session_id>/generate', methods=['POST'])
def generate_output(session_id):
    data = request.get_json() or {}
    output_filename = data.get('filename')
    
    try:
        result = pipeline.generate_output(session_id, output_filename)
        return jsonify(result)
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@api_bp.route('/download/<session_id>/<filename>', methods=['GET'])
def download_file(session_id, filename):
    state = pipeline.get_session(session_id)
    if not state or not state.output_path:
        return jsonify({"error": "File not found"}), 404
    
    output_path = Path(state.output_path)
    if output_path.name != filename:
        return jsonify({"error": "File not found"}), 404
    
    if not output_path.exists():
        return jsonify({"error": "File not found"}), 404
    
    return send_file(
        str(output_path),
        as_attachment=True,
        download_name=filename,
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    )


@api_bp.route('/session/<session_id>/template-info', methods=['GET'])
def get_template_info(session_id):
    state = pipeline.get_session(session_id)
    if not state or not state.template_analyzer:
        return jsonify({"success": False, "error": "Template not loaded"}), 404
    
    return jsonify({
        "success": True,
        "named_ranges": state.template_analyzer.to_dict(),
        "schema": state.template_analyzer.get_field_schema()
    })


@api_bp.route('/session/<session_id>/dictionary-info', methods=['GET'])
def get_dictionary_info(session_id):
    state = pipeline.get_session(session_id)
    if not state or not state.dictionary_manager:
        return jsonify({"success": False, "error": "Dictionary not loaded"}), 404
    
    return jsonify({
        "success": True,
        "mappings": state.dictionary_manager.to_dict()
    })


@api_bp.route('/session/<session_id>/preview', methods=['GET'])
def preview_mapping(session_id):
    state = pipeline.get_session(session_id)
    if not state or not state.template_analyzer:
        return jsonify({"success": False, "error": "Template not loaded"}), 404
    
    if not state.extracted_data:
        return jsonify({"success": False, "error": "No extracted data"}), 404
    
    writer = ExcelWriter(state.template_path)
    preview = writer.preview_mapping(state.extracted_data)
    
    return jsonify({
        "success": True,
        "preview": preview
    })