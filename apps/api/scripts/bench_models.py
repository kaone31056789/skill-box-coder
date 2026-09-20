import sys, time; sys.path.insert(0,'.')
from genesis.agents.llm import get_llm, LLMError
from genesis.agents.schemas import HypothesisSet, GeneratedCode
from genesis.agents.codegen import CODE_CONTRACT

CANDIDATES = [
    "stealth/ox-alpha",
    "deepseek/deepseek-v4-flash-0731",
    "nvidia/nemotron-3-super-120b-a12b:free",
    "nvidia/nemotron-3-ultra-550b-a55b:free",
    "nvidia/nemotron-3-nano-30b-a3b:free",
    "qwen/qwen3.7-flash",
    "openai/gpt-oss-120b",
    "google/gemma-4-31b-it:free",
]
llm = get_llm()
Q = "Can we improve network anomaly detection while reducing false positives?"
CODE_TASK = ("Write a self-contained scikit-learn experiment comparing kNN and RandomForest "
             "under feature scaling.\n\n" + CODE_CONTRACT + "\nReturn JSON with a 'code' field.")

print(f"{'MODEL':<44}{'HYPOTH':>9}{'CODE':>9}  NOTES")
print("-"*86)
for m in CANDIDATES:
    llm.model_chain = [m]
    notes, hyp_t, code_t = [], None, None
    try:
        t=time.perf_counter()
        r=llm.complete_json("You are SCIENTIST.", f"Question: {Q}\n\nPropose 3 competing hypotheses.",
                            HypothesisSet, max_attempts=1, temperature=0.7)
        hyp_t=time.perf_counter()-t
        if len(r.hypotheses)<2: notes.append(f"only {len(r.hypotheses)} hyp")
    except LLMError as e:
        s=str(e); notes.append("429" if "429" in s else "404" if "404" in s else "no-json" if "JSON" in s or "empty" in s else s[:34])
    if hyp_t:
        try:
            t=time.perf_counter()
            c=llm.complete_json("You are ENGINEER.", CODE_TASK, GeneratedCode, max_attempts=1,
                                temperature=0.3, max_tokens=12000)
            code_t=time.perf_counter()-t
            if "result.json" not in c.code: notes.append("bad code")
        except LLMError as e:
            s=str(e); notes.append("code:"+("429" if "429" in s else "no-json" if "JSON" in s or "empty" in s else s[:24]))
    h=f"{hyp_t:.1f}s" if hyp_t else "FAIL"
    c=f"{code_t:.1f}s" if code_t else ("FAIL" if hyp_t else "-")
    print(f"{m:<44}{h:>9}{c:>9}  {', '.join(notes) or 'ok'}")
