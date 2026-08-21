# Operational amendment 001 — LLM JSON completion ceiling

`POST_FREEZE_OPERATIONAL_AMENDMENT_001` overlays only
`/llm/max_output_tokens`, from 768 to 1024. The original `formal.json` is
preserved byte for byte. Methodological logic and H1/H2/H3 are unchanged, but
an inference runtime parameter that belonged to the formal freeze is changed
and is therefore recorded explicitly.

The choice was not based on detection rate, detection delay, H1/H2/H3, or
IDV(13) performance. All 294 preserved COMPLETE responses ended below the old
ceiling; their observed maximum was 729 tokens. The only response reaching 768
ended with `finish_reason=length` and incomplete JSON serialization.

Resume is component-scoped. TARGET simulationRun 58 reuses its immutable
COMPLETE DPCA result, preserves LLM attempt 0001 as FAILED, and may create LLM
attempt 0002 from window `k=0` only after the synthetic technical acceptance
and operational gates pass.

The acceptance launch on 2026-08-16 was blocked before inference because only
1259 MiB of GPU memory was free and llama.cpp offloaded 0/29 layers. Its FAIL
artifact records `inference_count=0`; the required single synthetic inference
is still pending, and the real-start gate remains blocked.

After a clean GPU precheck, the single required synthetic inference passed on
2026-08-16 with 29/29 layers offloaded, 567 completion tokens, JSON parser
PASS, and `finish_reason=stop`. Network isolation and zero access to TARGET and
fault-free testing data were verified. The earlier zero-inference FAIL remains
preserved as historical technical evidence.
