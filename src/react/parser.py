from __future__ import annotations

import json
import re

from langchain_core.output_parsers import BaseOutputParser


class ReActOutputParser(BaseOutputParser[tuple[str, str, dict]]):
    def parse(self, text: str) -> tuple[str, str, dict]:
        thought_match = re.search(r"Thought:\s*(.*?)(?=\nAction:|\Z)", text, re.DOTALL)
        action_match  = re.search(r"Action:\s*(.*?)(?=\nAction Input:|\Z)", text, re.DOTALL)
        input_match   = re.search(r"Action Input:\s*(\{.*?\})", text, re.DOTALL)

        thought      = thought_match.group(1).strip() if thought_match else ""
        action       = action_match.group(1).strip()  if action_match  else ""
        action_input = json.loads(input_match.group(1)) if input_match else {}

        if not action:
            return thought, "finish", {"answer": text}

        return thought, action, action_input

    @property
    def _type(self) -> str:
        return "react_output_parser"


_parser = ReActOutputParser()


def parse_llm_output(text: str) -> tuple[str, str, dict]:
    return _parser.parse(text)
