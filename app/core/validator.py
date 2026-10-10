from pydantic import BaseModel, Field, field_validator, ValidationError
from typing import Dict, List, Any, Optional, Union, Type
from datetime import date, datetime
import json
import jsonschema
from jsonschema import validate, ValidationError as JsonSchemaValidationError
from app.core.template_analyzer import NamedRange
from app.core.dictionary import FieldMapping


class DynamicField(BaseModel):
    value: Any = None
    data_type: str = "string"
    is_valid: bool = True
    errors: List[str] = []
    warnings: List[str] = []


class TableRow(BaseModel):
    cells: Dict[str, Any] = {}
    is_valid: bool = True
    errors: List[str] = []
    warnings: List[str] = []


class TableData(BaseModel):
    headers: List[str] = []
    rows: List[TableRow] = []
    is_valid: bool = True
    errors: List[str] = []
    warnings: List[str] = []


class ExtractionResult(BaseModel):
    fields: Dict[str, DynamicField] = {}
    tables: Dict[str, TableData] = {}
    raw_json: Dict[str, Any] = {}
    is_valid: bool = True
    errors: List[str] = []
    warnings: List[str] = []


class DataValidator:
    def __init__(self, template_analyzer, dictionary_manager):
        self.template_analyzer = template_analyzer
        self.dictionary_manager = dictionary_manager
        self._type_map = {
            'string': str,
            'number': float,
            'integer': int,
            'date': date,
            'datetime': datetime,
            'boolean': bool,
        }
    
    def validate(self, extracted_data: Dict[str, Any]) -> ExtractionResult:
        result = ExtractionResult(raw_json=extracted_data)
        named_ranges = self.template_analyzer.get_named_ranges()
        
        for name, nr in named_ranges.items():
            value = extracted_data.get(name)
            mapping = self.dictionary_manager.get_mapping(name)
            
            if nr.is_table:
                table_result = self._validate_table(name, value, nr, mapping)
                result.tables[name] = table_result
                if not table_result.is_valid:
                    result.is_valid = False
                    result.errors.extend(table_result.errors)
                result.warnings.extend(table_result.warnings)
            else:
                field_result = self._validate_field(name, value, nr, mapping)
                result.fields[name] = field_result
                if not field_result.is_valid:
                    result.is_valid = False
                    result.errors.extend(field_result.errors)
                result.warnings.extend(field_result.warnings)
        
        return result
    
    def _validate_field(self, name: str, value: Any, nr: NamedRange, mapping: Optional[FieldMapping]) -> DynamicField:
        field = DynamicField(value=value, data_type=nr.data_type)
        
        if mapping:
            is_valid, errors = self.dictionary_manager.validate_field(name, value)
            field.is_valid = is_valid
            field.errors = errors
            if mapping.data_type:
                field.data_type = mapping.data_type
        
        if value is not None:
            field = self._normalize_field(field, mapping)
        
        return field
    
    def _normalize_field(self, field: DynamicField, mapping: Optional[FieldMapping]) -> DynamicField:
        target_type = mapping.data_type if mapping else field.data_type
        
        if field.value is None:
            return field
        
        try:
            if target_type == "number":
                if isinstance(field.value, str):
                    field.value = float(field.value.replace(',', '.').replace(' ', ''))
                else:
                    field.value = float(field.value)
            
            elif target_type == "integer":
                if isinstance(field.value, str):
                    field.value = int(float(field.value.replace(',', '.').replace(' ', '')))
                else:
                    field.value = int(field.value)
            
            elif target_type == "date":
                if isinstance(field.value, str):
                    for fmt in ['%Y-%m-%d', '%d.%m.%Y', '%d/%m/%Y', '%Y/%m/%d']:
                        try:
                            d = datetime.strptime(field.value, fmt).date()
                            field.value = d.strftime('%d.%m.%Y')
                            break
                        except ValueError:
                            continue
                    else:
                        field.errors.append(f"Could not parse date: {field.value}")
                        field.is_valid = False
            
            elif target_type == "boolean":
                if isinstance(field.value, str):
                    field.value = field.value.lower() in ['true', 'yes', '1', 'да', 'истина']
                else:
                    field.value = bool(field.value)
            
            elif target_type == "string":
                field.value = str(field.value).strip()
        
        except Exception as e:
            field.errors.append(f"Normalization error: {str(e)}")
            field.is_valid = False
        
        return field
    
    def _validate_table(self, name: str, value: Any, nr: NamedRange, mapping: Optional[FieldMapping]) -> TableData:
        table = TableData(headers=nr.table_headers)
        
        if value is None:
            table.errors.append("Table data is missing")
            table.is_valid = False
            return table
        
        if not isinstance(value, list):
            table.errors.append("Table data must be an array")
            table.is_valid = False
            return table
        
        for i, row_data in enumerate(value):
            if not isinstance(row_data, dict):
                table.errors.append(f"Row {i} must be an object")
                table.is_valid = False
                continue
            
            row = TableRow(cells={})
            for header in nr.table_headers:
                cell_value = row_data.get(header)
                cell_mapping = None
                
                if mapping and mapping.validation_rules:
                    cell_mapping = FieldMapping(
                        field_name=header,
                        description="",
                        entity_type="",
                        extraction_hint="",
                        data_type=mapping.validation_rules.get(f"{header}_type", "string"),
                        validation_rules=mapping.validation_rules.get(header, {})
                    )
                
                field_result = self._validate_field(f"{name}.{header}", cell_value, nr, cell_mapping)
                row.cells[header] = field_result.value
                
                if not field_result.is_valid:
                    row.is_valid = False
                    row.errors.extend(field_result.errors)
            
            table.rows.append(row)
            
            if not row.is_valid:
                table.is_valid = False
                table.errors.extend(row.errors)
        
        return table
    
    def create_pydantic_model(self, schema: Dict[str, Any]) -> Type[BaseModel]:
        fields = {}
        
        for name, prop in schema.get('properties', {}).items():
            prop_type = prop.get('type', 'string')
            
            if prop_type == 'array':
                items = prop.get('items', {})
                if items.get('type') == 'object':
                    fields[name] = (List[Dict[str, Any]], Field(default_factory=list))
                else:
                    fields[name] = (List[Any], Field(default_factory=list))
            elif prop_type == 'number':
                fields[name] = (Optional[float], Field(default=None))
            elif prop_type == 'integer':
                fields[name] = (Optional[int], Field(default=None))
            elif prop_type == 'boolean':
                fields[name] = (Optional[bool], Field(default=None))
            else:
                fields[name] = (Optional[str], Field(default=None))
        
        return type('DynamicModel', (BaseModel,), {'__annotations__': fields})
    
    def validate_with_pydantic(self, data: Dict[str, Any], schema: Dict[str, Any]) -> tuple[bool, List[str], Dict[str, Any]]:
        model_class = self.create_pydantic_model(schema)
        
        try:
            validated = model_class(**data)
            return True, [], validated.model_dump()
        except ValidationError as e:
            errors = [f"{err['loc'][0]}: {err['msg']}" for err in e.errors()]
            return False, errors, data


def validate_extraction(extracted_data: Dict[str, Any], template_analyzer, dictionary_manager) -> ExtractionResult:
    validator = DataValidator(template_analyzer, dictionary_manager)
    return validator.validate(extracted_data)