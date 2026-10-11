#!/usr/bin/env python3
"""Read-only bounded Cloudflare Worker source excerpts for quota repair review."""
import json, pathlib, re, sys
BASE=pathlib.Path("/volume1/docker/RG_ALERTS_DEPLOY/cloudflare-alerts/src")
TARGETS={
"index.js":[(105,140),(295,340),(670,725),(1515,1650)],
"quota-entry.js":[(20,65),(120,145),(545,575),(640,715)],
"moderation-ops.js":[(955,1000),(1100,1150),(1370,1405)],
"calendar-entry.js":[(1,90)],
}
SENSITIVE=re.compile(r"(authorization|api[_-]?key|api[_-]?token|bot[_-]?token|secret|password|private[_-]?key|bearer)",re.I)
STRING=re.compile(r"""(["'`])(?:(?!\1).)*?\1""")
def safe(line):
    if SENSITIVE.search(line):
        return "[REDACTED_SENSITIVE_LINE]"
    if len(line)>250:
        return line[:250]+" [TRUNCATED]"
    return line
def main():
    if "--selftest" in sys.argv:
        assert safe("const secret = 'abc'")=="[REDACTED_SENSITIVE_LINE]"
        assert safe("return await doStub.fetch(request)")=="return await doStub.fetch(request)"
        print('{"selftest":"PASS","read_only":true}')
        return
    output={"report":"RG_WORKER_SOURCE_CONTEXT_V1","read_only":True,"sources":[]}
    for name,spans in TARGETS.items():
        path=BASE/name
        if path.is_symlink() or not path.is_file() or path.stat().st_size>1500000:
            output["sources"].append({"file":name,"error":"not_readable"});continue
        lines=path.read_text(encoding="utf-8",errors="replace").splitlines()
        snippets=[]
        for a,b in spans:
            snippets.append({"range":f"{a}-{b}","lines":[f"{i}: {safe(lines[i-1])}" for i in range(a,min(b,len(lines))+1)]})
        output["sources"].append({"file":name,"total_lines":len(lines),"snippets":snippets})
    print(json.dumps(output,ensure_ascii=False,indent=2))
if __name__=="__main__":
    main()
