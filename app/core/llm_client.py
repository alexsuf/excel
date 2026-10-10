import os
import json
import re
import time
import logging
import sys
import threading
from datetime import datetime
from typing import Dict, List, Optional, Any, Tuple
from pathlib import Path
import requests
from openai import OpenAI
from app.core.config import settings
from app.core.doc_extractors import (
    DocumentExtraction,
    DocumentTextExtractor,
    get_document_extractor,
)


_llm_logger = None


class _FlushFileHandler(logging.FileHandler):
    def emit(self, record):
        super().emit(record)
        self.flush()
        try:
            import os
            os.fsync(self.stream.fileno())
        except Exception:
            pass


def _get_llm_logger():
    global _llm_logger
    if _llm_logger is not None:
        return _llm_logger
    logger = logging.getLogger("llm")
    logger.setLevel(logging.DEBUG)
    if logger.handlers:
        _llm_logger = logger
        return logger
    configured_dir = Path(settings.output_dir)
    try:
        configured_dir.mkdir(parents=True, exist_ok=True)
        log_path = configured_dir / "llm.log"
    except (OSError, PermissionError):
        log_path = Path("llm.log")
    try:
        file_handler = _FlushFileHandler(str(log_path), encoding="utf-8")
    except Exception:
        file_handler = _FlushFileHandler("llm.log", encoding="utf-8")
    file_handler.setLevel(logging.DEBUG)
    formatter = logging.Formatter("%(asctime)s | %(levelname)-7s | %(message)s", datefmt="%Y-%m-%d %H:%M:%S")
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)
    console_handler = logging.StreamHandler(sys.stderr)
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)
    _llm_logger = logger
    abs_path = Path(log_path).resolve()
    logger.info("LLM logger initialized, output: %s", abs_path)
    sys.stderr.write(f"[llm] LOG FILE: {abs_path}\n")
    sys.stderr.flush()
    return logger


def _llm_debug(msg: str):
    _get_llm_logger().debug("[llm] %s", msg)


class LLMClient:
    def __init__(self, extractor: Optional[DocumentTextExtractor] = None):
        self.log = _get_llm_logger()
        self.model = settings.llm_model
        self.max_retries = 3
        self.retry_delay = 5
        self.extractor = extractor or get_document_extractor()
        self.log.info("LLM client created: model=%s base=%s timeout=%ds retries=%d ocr=%s",
                       self.model, settings.llm_api_base, settings.llm_timeout, self.max_retries,
                       self.extractor.ocr_available)
        self.client = OpenAI(
            api_key=settings.llm_api_key,
            base_url=settings.llm_api_base,
            timeout=settings.llm_timeout
        )

    def extract_from_files(self, file_paths: List[str], prompt: str, schema: Dict[str, Any]) -> Dict[str, Any]:
        self.log.info(">>> extract_from_files ENTERED, files=%d, model=%s", len(file_paths), self.model)
        sys.stderr.write(f"[llm][{time.strftime('%H:%M:%S')}] extract_from_files ENTERED: {len(file_paths)} files, model={self.model}\n")
        sys.stderr.flush()

        self.log.info("Step 1/6: Building schema text...")
        sys.stderr.write(f"[llm][{time.strftime('%H:%M:%S')}] Step 1/6: Building schema text...\n")
        sys.stderr.flush()
        schema_text = (
            f"Return JSON matching this schema:\n"
            f"{json.dumps(schema, ensure_ascii=False, indent=2)}\n\n"
            f"If a field is not found, set it to null. For tables, return an array of objects."
        )
        self.log.debug("Schema text built: %d chars", len(schema_text))
        sys.stderr.write(f"[llm][{time.strftime('%H:%M:%S')}] Schema built: {len(schema_text)} chars\n")
        sys.stderr.flush()

        self.log.info("Step 2/6: Extracting text from %d files...", len(file_paths))
        sys.stderr.write(f"[llm][{time.strftime('%H:%M:%S')}] Step 2/6: Extracting text from {len(file_paths)} files...\n")
        sys.stderr.flush()

        extractions = [self.extractor.extract(fp) for fp in file_paths]
        vision_files = [e for e in extractions if e.needs_vision and e.is_empty]
        text_files = [e for e in extractions if not e.is_empty]

        for item in extractions:
            meta = item.metadata
            self.log.info(
                "  %s: %d chars, pages=%s text_pages=%s ocr_pages=%s empty_pages=%s%s",
                item.display_name, len(item.content), meta.get("pages", "-"),
                meta.get("text_pages", "-"), meta.get("ocr_pages", "-"),
                meta.get("empty_pages", "-"), f" ERROR={item.error}" if item.error else "",
            )
            if item.error:
                sys.stderr.write(
                    f"[llm][{time.strftime('%H:%M:%S')}]   {item.display_name}: {item.error}\n")

        if vision_files:
            self.log.info("Vision fallback needed for: %s",
                          ", ".join(e.display_name for e in vision_files))
            sys.stderr.write(f"[llm][{time.strftime('%H:%M:%S')}] Vision fallback for {len(vision_files)} file(s)\n")
            sys.stderr.flush()

        if text_files or vision_files:
            messages = self._build_messages(prompt, schema_text, text_files, vision_files)
        else:
            self.log.error("No usable content extracted from any document")
            raise ValueError(
                "Не удалось извлечь текст ни из одного документа "
                "(возможно, это сканы без текстового слоя и недоступен OCR)"
            )

        total_chars = 0
        image_count = 0
        for m in messages:
            c = m.get("content", "")
            if isinstance(c, str):
                total_chars += len(c)
            elif isinstance(c, list):
                for p in c:
                    if not isinstance(p, dict):
                        continue
                    if p.get("type") == "text":
                        total_chars += len(p.get("text", ""))
                    elif p.get("type") == "image_url":
                        image_count += 1
        token_estimate = total_chars // 2
        self.log.info("Messages built: %d, text chars: %d (~%d tokens), images: %d",
                      len(messages), total_chars, token_estimate, image_count)

        self.log.info("Step 3/6: Logging full request details...")
        sys.stderr.write(f"[llm][{time.strftime('%H:%M:%S')}] Step 3/6: Logging full request details\n")
        sys.stderr.flush()

        self.log.info("=" * 60)
        self.log.info("LLM Extraction Request — FULL DETAILS")
        self.log.info("=" * 60)
        self.log.info("Timestamp: %s", datetime.now().isoformat())
        self.log.info("Model: %s", self.model)
        self.log.info("API Base: %s", settings.llm_api_base)
        self.log.info("Timeout: %ds", settings.llm_timeout)
        self.log.info("Messages count: %d, text chars: %d (~%d tokens), images: %d",
                      len(messages), total_chars, token_estimate, image_count)
        self.log.info("Parameters: temperature=0.1, max_tokens=%d, response_format=json_object",
                      settings.llm_max_tokens)
        self.log.info("-" * 60)

        for i, msg in enumerate(messages):
            role = msg.get("role", "unknown")
            content = msg.get("content", "")
            if isinstance(content, str):
                self.log.info("[msg %d/%s] (%d chars):", i, role, len(content))
                self.log.info(content)
            elif isinstance(content, list):
                for j, part in enumerate(content):
                    if not isinstance(part, dict):
                        continue
                    if part.get("type") == "text":
                        text = part.get("text", "")
                        self.log.info("[msg %d/%s/%d/text] (%d chars):", i, role, j, len(text))
                        self.log.info(text)
                    elif part.get("type") == "image_url":
                        url = part.get("image_url", {}).get("url", "")
                        self.log.info("[msg %d/%s/%d/image] (%d chars base64)", i, role, j, len(url))

        self.log.info("-" * 60)
        self.log.info("END OF FULL REQUEST")
        self.log.info("=" * 60)

        self.log.info("Step 4/6: Sending request to %s (max %d retries)...", settings.llm_api_base, self.max_retries)
        sys.stderr.write(f"[llm][{time.strftime('%H:%M:%S')}] Step 4/6: Sending request to {settings.llm_api_base} (retries={self.max_retries})\n")
        sys.stderr.flush()
        
        last_exception = None
        for attempt in range(self.max_retries):
            start = time.time()
            stopped = False
            def _heartbeat():
                while not stopped:
                    elapsed = time.time() - start
                    sys.stderr.write(f"[llm][{time.strftime('%H:%M:%S')}] WAITING for LLM response... ({elapsed:.0f}s elapsed, attempt {attempt+1}/{self.max_retries})\n")
                    sys.stderr.flush()
                    time.sleep(1)
            hb_thread = threading.Thread(target=_heartbeat, daemon=True)
            try:
                hb_thread.start()
                response = self.client.chat.completions.create(
                    model=self.model,
                    messages=messages,
                    temperature=0.1,
                    response_format={"type": "json_object"},
                    max_tokens=settings.llm_max_tokens
                )
                stopped = True
                hb_thread.join(timeout=2)
                
                elapsed = time.time() - start
                self.log.info("Response received in %.1fs (attempt %d)", elapsed, attempt + 1)
                sys.stderr.write(f"[llm][{time.strftime('%H:%M:%S')}] Response received in {elapsed:.1f}s (attempt {attempt+1}/{self.max_retries})\n")
                sys.stderr.flush()

                message = response.choices[0].message
                content, origin = self._extract_payload(message)
                if content is None:
                    raise ValueError(
                        "LLM returned neither content nor reasoning "
                        f"(finish_reason={response.choices[0].finish_reason})"
                    )

                self.log.info("Step 5/6: Raw LLM response (%d chars, from %s):", len(content), origin)
                self.log.info(content)

                self.log.info("Step 6/6: Parsing JSON result...")
                sys.stderr.write(f"[llm][{time.strftime('%H:%M:%S')}] Step 6/6: Parsing JSON result...\n")
                sys.stderr.flush()
                result = self._parse_json(content)
                self.log.info("Parsed %d fields from LLM response", len(result))
                for k, v in result.items():
                    self.log.debug("[%s] = %s", k, str(v)[:200])
                self.log.info("=" * 60)
                self.log.info("<<< extract_from_files DONE (attempt %d)", attempt + 1)
                sys.stderr.write(f"[llm][{time.strftime('%H:%M:%S')}] extract_from_files DONE\n")
                sys.stderr.flush()
                return result
                
            except Exception as e:
                stopped = True
                elapsed = time.time() - start
                is_vision_error = (
                    isinstance(e, (TypeError, AttributeError))
                    and image_count > 0
                    and attempt == 0
                )
                last_exception = e
                if is_vision_error:
                    self.log.warning(
                        "Vision not supported, retrying without image parts: %s", str(e)
                    )
                    sys.stderr.write("[llm] Vision not supported by model, retrying without images\n")
                    sys.stderr.flush()
                    text_only_files = [e for e in extractions if not e.needs_vision]
                    messages = self._build_messages(prompt, schema_text, text_only_files, [])
                    image_count = 0
                    continue
                self.log.warning("Attempt %d/%d FAILED after %.1fs: %s", attempt + 1, self.max_retries, elapsed, str(e))
                sys.stderr.write(f"[llm][{time.strftime('%H:%M:%S')}] Attempt {attempt+1}/{self.max_retries} FAILED after {elapsed:.1f}s: {e}\n")
                sys.stderr.flush()
                try:
                    hb_thread.join(timeout=1)
                except Exception:
                    pass
                
                if attempt < self.max_retries - 1:
                    delay = self.retry_delay * (2 ** attempt)
                    self.log.info("Retrying in %ds...", delay)
                    sys.stderr.write(f"[llm][{time.strftime('%H:%M:%S')}] Retrying in {delay}s...\n")
                    sys.stderr.flush()
                    time.sleep(delay)
        
        self.log.error("All %d attempts FAILED. Last error: %s", self.max_retries, str(last_exception))
        sys.stderr.write(f"[llm][{time.strftime('%H:%M:%S')}] All {self.max_retries} attempts FAILED: {last_exception}\n")
        sys.stderr.flush()
        raise last_exception

    @staticmethod
    def _extract_payload(message) -> Tuple[Optional[str], str]:
        content = getattr(message, "content", None)
        if isinstance(content, str) and content.strip():
            return content, "content"
        reasoning = getattr(message, "reasoning", None)
        if isinstance(reasoning, str) and reasoning.strip():
            return reasoning, "reasoning"
        if content is not None and not isinstance(content, str):
            return json.dumps(content, ensure_ascii=False), "content(json)"
        return None, "none"

    @staticmethod
    def _parse_json(content: str) -> Dict[str, Any]:
        text = content.strip()
        try:
            parsed = json.loads(text)
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError:
            pass

        fenced = re.search(r"```(?:json)?\s*(.+?)```", text, re.DOTALL)
        if fenced:
            try:
                parsed = json.loads(fenced.group(1).strip())
                if isinstance(parsed, dict):
                    return parsed
            except json.JSONDecodeError:
                text = fenced.group(1).strip()

        start = text.find('{')
        while start != -1:
            depth = 0
            in_string = False
            escaped = False
            for idx in range(start, len(text)):
                ch = text[idx]
                if in_string:
                    if escaped:
                        escaped = False
                    elif ch == '\\':
                        escaped = True
                    elif ch == '"':
                        in_string = False
                    continue
                if ch == '"':
                    in_string = True
                elif ch == '{':
                    depth += 1
                elif ch == '}':
                    depth -= 1
                    if depth == 0:
                        try:
                            parsed = json.loads(text[start:idx + 1])
                            if isinstance(parsed, dict):
                                return parsed
                        except json.JSONDecodeError:
                            break
            start = text.find('{', start + 1)

        raise ValueError(f"Could not parse JSON from LLM response: {text[:500]}")

    def _build_messages(self, prompt: str, schema_text: str,
                        text_files: List[DocumentExtraction],
                        vision_files: List[DocumentExtraction]) -> List[Dict[str, Any]]:
        system_prompt = self._augment_prompt(prompt)
        budget = self._document_budget(system_prompt, schema_text)
        parts: List[Dict[str, Any]] = [{"type": "text", "text": schema_text}]
        used = 0

        for item in text_files:
            header = f"\n\n===== ДОКУМЕНТ: {item.display_name} =====\n"
            body = self._truncate(item.content, max(budget - used - len(header), 2000))
            if not body:
                continue
            used += len(header) + len(body)
            parts.append({"type": "text", "text": header + body})
            self.log.info("  text part for %s: %d chars (budget left %d)",
                          item.display_name, len(body), budget - used)

        for item in vision_files:
            if not settings.llm_vision_fallback:
                continue
            pages = self.extractor.render_pages_as_images(
                item.file_path,
                max_pages=settings.llm_vision_max_pages,
                zoom=settings.llm_vision_zoom,
            )
            if not pages:
                continue
            self.log.info("  vision part for %s: %d page image(s)", item.display_name, len(pages))
            parts.append({
                "type": "text",
                "text": f"\n\n===== ДОКУМЕНТ (СКАН, СТРАНИЦЫ КАК КАРТИНКИ): {item.display_name} =====\n"
                        f"Текстовый слой отсутствует. Прочитай реквизиты и таблицу прямо с изображений страниц.\n",
            })
            for page_no, mime, b64 in pages:
                parts.append({
                    "type": "text",
                    "text": f"[{item.display_name}: страница {page_no}]",
                })
                parts.append({
                    "type": "image_url",
                    "image_url": {"url": f"data:{mime};base64,{b64}", "detail": "high"},
                })

        return [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": parts},
        ]

    @staticmethod
    def _augment_prompt(prompt: str) -> str:
        return "\n".join([
            prompt,
            "",
            "ВАЖНО ПРИ РАСПОЗНАВАНИИ:",
            "1. Документы получены из PDF/DOCX автоматически, поэтому в тексте возможны артефакты OCR:",
            "   разрывы слов, слипшиеся переносы, неразрывные пробелы, ошибки в знаках препинания.",
            "   Восстанавливай смысл, но никогда не выдумывай значения, которых нет в тексте.",
            "2. Числа записывай числами (без пробелов, без знака валюты, с точкой как десятичным разделителем).",
            "3. Не пересчитывай итоги самостоятельно: бери готовые итоговые строки из документа.",
            "4. Если поле отсутствует в документе — верни null. Не подставляй значения по аналогии.",
            "5. Табличные строки возвращай в порядке документа, каждая строка — отдельный объект.",
            "6. Верни ТОЛЬКО JSON-объект без пояснений и без markdown-обёртки.",
        ])

    def _document_budget(self, system_prompt: str, schema_text: str) -> int:
        overhead = len(system_prompt) + len(schema_text) + 4000
        available = int(settings.llm_context_tokens * settings.llm_chars_per_token)
        available -= overhead
        available -= settings.llm_max_output_tokens
        return max(available, 20000)

    @staticmethod
    def _truncate(text: str, limit: int) -> str:
        if len(text) <= limit:
            return text
        head = limit // 2
        tail = limit - head
        return (
            text[:head]
            + f"\n\n[... СОДЕРЖИМОЕ СОКРАЩЕНО: пропущено {len(text) - limit} символов ...]\n\n"
            + text[-tail:]
        )

    def validate_extraction(self, extracted_data: Dict[str, Any], schema: Dict[str, Any]) -> Dict[str, Any]:
        validation_prompt = f"""
        Validate the following extracted data against the schema.
        Return a JSON with:
        - valid: boolean
        - errors: array of error messages
        - warnings: array of warning messages
        - corrected_data: the corrected data (if any corrections were made)

        Schema: {json.dumps(schema, ensure_ascii=False)}
        Data: {json.dumps(extracted_data, ensure_ascii=False, indent=2)}
        """
        response = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": "You are a data validation expert. Validate JSON data against a schema."},
                {"role": "user", "content": validation_prompt}
            ],
            temperature=0,
            response_format={"type": "json_object"}
        )
        return json.loads(response.choices[0].message.content)


def get_llm_client() -> LLMClient:
    return LLMClient()