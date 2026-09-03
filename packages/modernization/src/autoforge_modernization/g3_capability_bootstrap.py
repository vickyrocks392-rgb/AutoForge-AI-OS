"""G.3 Capability Bootstrap - populate registry from real repository content."""
from __future__ import annotations
import os, re
from datetime import datetime, timezone
from autoforge_modernization.capability_registry import (
    TechnologyCapabilityRegistry, TechnologyCapability,
    CapabilityState, CapabilityLevel,
)
def _utc_now(): return datetime.now(timezone.utc)
def _loc(c):
    lines = c.split("\n"); return len(lines), sum(1 for l in lines if l.strip())
def _detect(root):
    techs = {}
    for dp, _, fns in os.walk(root):
        if any(x in dp for x in ["target",".git","node_modules","__pycache__"]): continue
        for fn in fns:
            ext = os.path.splitext(fn)[1].lower()
            path = os.path.join(dp, fn); rel = os.path.relpath(path, root)
            try: content = open(path, errors="replace").read()
            except: continue
            _, nloc = _loc(content)
            if ext in (".cbl",".cob"):
                if any(k in content.upper() for k in ["IDENTIFICATION DIVISION","PROCEDURE DIVISION","DATA DIVISION","PROGRAM-ID"]):
                    techs.setdefault("COBOL", {"files":0,"LOC":0,"sample":[]})
                    techs["COBOL"]["files"] += 1; techs["COBOL"]["LOC"] += nloc
                    if len(techs["COBOL"]["sample"]) < 3: techs["COBOL"]["sample"].append(rel)
            elif ext == ".jcl":
                if re.search(r"^//\s*\w+\s+(JOB|EXEC|DD|PROC)\b", content, re.MULTILINE):
                    techs.setdefault("JCL", {"files":0,"LOC":0,"sample":[]})
                    techs["JCL"]["files"] += 1; techs["JCL"]["LOC"] += nloc
                    if len(techs["JCL"]["sample"]) < 3: techs["JCL"]["sample"].append(rel)
            elif ext == ".bms":
                if "DFHMSD" in content.upper() or "DFHMDF" in content.upper():
                    techs.setdefault("BMS", {"files":0,"LOC":0,"sample":[]})
                    techs["BMS"]["files"] += 1; techs["BMS"]["LOC"] += nloc
                    if len(techs["BMS"]["sample"]) < 3: techs["BMS"]["sample"].append(rel)
            elif ext in (".ddl",".dcl",".sql"):
                if any(k in content.upper() for k in ["CREATE TABLE","CREATE INDEX","SELECT","INSERT INTO","EXEC SQL"]):
                    techs.setdefault("DB2", {"files":0,"LOC":0,"sample":[]})
                    techs["DB2"]["files"] += 1; techs["DB2"]["LOC"] += nloc
                    if len(techs["DB2"]["sample"]) < 3: techs["DB2"]["sample"].append(rel)
            elif ext == ".cpy":
                techs.setdefault("COPYBOOK", {"files":0,"LOC":0,"sample":[]})
                techs["COPYBOOK"]["files"] += 1; techs["COPYBOOK"]["LOC"] += nloc
                if len(techs["COPYBOOK"]["sample"]) < 3: techs["COPYBOOK"]["sample"].append(rel)
            elif ext in (".dbd",".psb"):
                techs.setdefault("IMS", {"files":0,"LOC":0,"sample":[]})
                techs["IMS"]["files"] += 1; techs["IMS"]["LOC"] += nloc
                if len(techs["IMS"]["sample"]) < 3: techs["IMS"]["sample"].append(rel)
            elif ext == ".csd":
                techs.setdefault("CICS", {"files":0,"LOC":0,"sample":[]})
                techs["CICS"]["files"] += 1; techs["CICS"]["LOC"] += nloc
                if len(techs["CICS"]["sample"]) < 3: techs["CICS"]["sample"].append(rel)
            elif ext in (".ca7",".controlm"):
                techs.setdefault("CONTROL_M", {"files":0,"LOC":0,"sample":[]})
                techs["CONTROL_M"]["files"] += 1
                if len(techs["CONTROL_M"]["sample"]) < 3: techs["CONTROL_M"]["sample"].append(rel)
    return techs


def bootstrap_registry(root, project_id="unknown"):
    techs = _detect(root)
    registry = TechnologyCapabilityRegistry(version="1.0.0")
    if "COBOL" in techs:
        registry.register(TechnologyCapability(technology_name="COBOL", version="COBOL-85/Enterprise", state=CapabilityState.PARTIALLY_SUPPORTED, level=CapabilityLevel.ANALYZE, analysis_confidence=0.95, transformation_confidence=0.65, detection_confidence=0.98, supported_constructs=["PERFORM","MOVE","IF","EVALUATE","COMPUTE","CALL","READ","WRITE","REWRITE","OPEN","CLOSE","COPY","WORKING-STORAGE","FILE-SECTION","LINKAGE-SECTION","EXEC SQL","EXEC CICS","GO TO","EXIT","STOP RUN","EXIT PROGRAM","GOBACK","STRING","UNSTRING","INSPECT","SET","ADD","SUBTRACT","DIVIDE","MULTIPLY"], unsupported_constructs=["EXEC CICS LINK (specialist)","EXEC CICS RETURN (specialist)","SORT/MERGE (specialist)","REPORT WRITER (specialist)","OCCURS DEPENDING ON (complex)"], assessment_method="deterministic_analyzer + LLM_semantic", evidence=_ev(techs["COBOL"], root), version_note="COBOL-85 baseline; Enterprise COBOL z/OS features partial"))
    if "JCL" in techs:
        registry.register(TechnologyCapability(technology_name="JCL", version="z/OS JCL", state=CapabilityState.PARTIALLY_SUPPORTED, level=CapabilityLevel.ANALYZE, analysis_confidence=0.92, transformation_confidence=0.60, detection_confidence=0.95, supported_constructs=["JOB","EXEC PGM","EXEC PROC","DD DSN","DD DISP","DD UNIT","DD SPACE","SET","IF/THEN/ELSE/ENDIF","INCLUDE","CNTL/ENDCNTL"], unsupported_constructs=["JES2/JES3 directives","GDG complex patterns","dynamic allocation","USS scripts"], assessment_method="deterministic_analyzer", evidence=_ev(techs["JCL"], root), version_note="z/OS JCL baseline; JES2/JES3 specifics require review"))
    if "BMS" in techs:
        registry.register(TechnologyCapability(technology_name="BMS", version="CICS BMS", state=CapabilityState.TOOL_REQUIRED, level=CapabilityLevel.DETECT, analysis_confidence=0.85, transformation_confidence=0.10, detection_confidence=0.90, supported_constructs=["DFHMSD","DFHMDF","MAPSET","FIELD"], unsupported_constructs=["CICS tx integration","BMS to HTML/React","Screen state mgmt"], assessment_method="heuristic_content_scan", evidence=_ev(techs["BMS"], root), registered_tool_name=None, version_note="BMS requires CICS env + UI modernization strategy"))
    if "DB2" in techs:
        registry.register(TechnologyCapability(technology_name="DB2", version="DB2 for z/OS", state=CapabilityState.PARTIALLY_SUPPORTED, level=CapabilityLevel.ANALYZE, analysis_confidence=0.90, transformation_confidence=0.55, detection_confidence=0.88, supported_constructs=["CREATE TABLE","CREATE INDEX","CREATE VIEW","SELECT","INSERT","UPDATE","DELETE","WHERE","JOIN","ORDER BY","GROUP BY","embedded SQL (EXEC SQL)"], unsupported_constructs=["Stored procedures (specialist)","Triggers (complex)","UDFs","DB2 optimizer hints","Native REST procedures"], assessment_method="deterministic_analyzer", evidence=_ev(techs["DB2"], root), version_note="DB2 for z/OS; PostgreSQL as target"))
    if "IMS" in techs:
        registry.register(TechnologyCapability(technology_name="IMS", version="IMS DB/TM", state=CapabilityState.UNSUPPORTED, level=CapabilityLevel.DETECT, analysis_confidence=0.0, transformation_confidence=0.0, detection_confidence=0.75, supported_constructs=["DBD","PSB"], unsupported_constructs=["HDAM/HIDAM","IMS TM","DL/I","IMS to relational"], assessment_method="file_extension_scan", evidence=[f"detected_in: {', '.join(techs['IMS']['sample'])}", f"files: {techs['IMS']['files']}"], version_note="IMS DB/TM requires specialist tooling"))
    if "CICS" in techs:
        registry.register(TechnologyCapability(technology_name="CICS", version="CICS TS", state=CapabilityState.TOOL_REQUIRED, level=CapabilityLevel.DETECT, analysis_confidence=0.50, transformation_confidence=0.0, detection_confidence=0.70, supported_constructs=["EXEC CICS (detection only)"], unsupported_constructs=["CICS tx programs","CICS LINK/RETURN/XCTL","CICS file control","CICS BMS","CICS to REST API"], assessment_method="content_scan", evidence=[f"detected_in: {', '.join(techs['CICS']['sample'])}", f"files: {techs['CICS']['files']}"], version_note="CICS requires architectural review + specialist tooling"))
    if "COPYBOOK" in techs:
        registry.register(TechnologyCapability(technology_name="COBOL_COPYBOOK", version="COBOL-85", state=CapabilityState.PARTIALLY_SUPPORTED, level=CapabilityLevel.ANALYZE, analysis_confidence=0.90, transformation_confidence=0.70, detection_confidence=0.95, supported_constructs=["01-level groups","05/77-level items","PIC clauses","VALUE clauses","REDEFINES"], unsupported_constructs=["COPY REPLACING (complex)","nested copybooks"], assessment_method="deterministic_analyzer", evidence=_ev(techs["COPYBOOK"], root), version_note="Copybooks analyzed as COBOL data division fragments"))
    if "CONTROL_M" in techs:
        registry.register(TechnologyCapability(technology_name="CONTROL_M", version="Control-M", state=CapabilityState.ENVIRONMENT_REQUIRED, level=CapabilityLevel.DETECT, analysis_confidence=0.0, transformation_confidence=0.0, detection_confidence=0.80, supported_constructs=["job definitions"], unsupported_constructs=["full Control-M scheduling"], assessment_method="file_extension_scan", evidence=[f"detected_in: {', '.join(techs['CONTROL_M']['sample'])}", f"files: {techs['CONTROL_M']['files']}"], version_note="Control-M requires Control-M env or replacement scheduler"))
    registry.total_technologies = len(registry.capabilities)
    registry.last_updated = _utc_now()
    return registry


def _ev(t, root): return [f"detected_in: {', '.join(t['sample'])}", f"files: {t['files']}", f"LOC: {t['LOC']}"]
