#!/usr/bin/env python3
import json
import sys

from translate_parallel import (
    API_TIMEOUT,
    MODEL,
    REASONING_EFFORT,
    build_translation_prompt,
    get_client,
)


def main():
    content = sys.stdin.read()
    prompt = build_translation_prompt(content)
    response = get_client().chat.completions.create(
        model=MODEL,
        messages=[{"role": "user", "content": prompt}],
        response_format={"type": "json_object"},
        temperature=0,
        max_tokens=8192,
        extra_body={
            "reasoning_effort": REASONING_EFFORT,
        },
        timeout=API_TIMEOUT,
    )
    result = response.choices[0].message.content
    print(json.dumps({"result": result}, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(str(e), file=sys.stderr, flush=True)
        raise
