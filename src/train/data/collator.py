from __future__ import annotations


def make_sft_collator(tokenizer, mlm: bool = False):
    from transformers import DataCollatorForLanguageModeling

    return DataCollatorForLanguageModeling(tokenizer=tokenizer, mlm=mlm)
