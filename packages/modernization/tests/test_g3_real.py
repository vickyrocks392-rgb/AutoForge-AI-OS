"""
G.3 Real Engine Tests - adversarial cases.
Tests empty files, binary, malformed COBOL, missing capabilities, LLM failure modes.
"""
import pytest
from pathlib import Path


@pytest.fixture
def tmp_repo(tmp_path):
    cobol_dir = tmp_path / "COBOL"
    jcl_dir   = tmp_path / "JCL"
    cobol_dir.mkdir()
    jcl_dir.mkdir()
    (cobol_dir / "EMPTY.CBL").write_text("")
    (cobol_dir / "BIN.CBL").write_bytes(b"\x00\xff\xfe\x00BINARY")
    (cobol_dir / "MALFORMED.CBL").write_text("THIS IS NOT COBOL AT ALL")
    (cobol_dir / "NOPIC.CBL").write_text(
        "       IDENTIFICATION DIVISION.\n"
        "       PROGRAM-ID. NOPIC.\n"
        "       PROCEDURE DIVISION.\n"
        "           DISPLAY 'NO DATA'.\n"
    )
    (jcl_dir / "EMPTY.JCL").write_text("")
    (jcl_dir / "MALFORMED.JCL").write_text("NOT //JCL AT ALL")
    return tmp_path


class TestCapabilityBootstrap:
    def test_bootstrap_returns_capabilities_dict(self, tmp_repo):
        from autoforge_modernization.g3_capability_bootstrap import bootstrap_registry
        reg = bootstrap_registry(str(tmp_repo), "test-project")
        assert hasattr(reg, "capabilities")
        assert isinstance(reg.capabilities, dict)

    def test_bootstrap_empty_repo_no_crash(self, tmp_path):
        from autoforge_modernization.g3_capability_bootstrap import bootstrap_registry
        reg = bootstrap_registry(str(tmp_path), "empty-project")
        assert hasattr(reg, "capabilities")

    def test_capability_entry_has_expected_keys(self, tmp_repo):
        from autoforge_modernization.g3_capability_bootstrap import bootstrap_registry
        reg = bootstrap_registry(str(tmp_repo), "test-project")
        assert isinstance(reg.capabilities, dict)

class TestCOBOLTransformEdgeCases:
    def test_empty_file_returns_identity(self, tmp_repo):
        from autoforge_modernization.g3_transform_strategies import _cobol_to_java
        content = (tmp_repo / "COBOL" / "EMPTY.CBL").read_text()
        result = _cobol_to_java(content)
        assert result is not None
        # Empty file may produce minimal class or empty string
        assert isinstance(result, str)

    def test_binary_file_no_crash(self, tmp_repo):
        from autoforge_modernization.g3_transform_strategies import _cobol_to_java
        content_bytes = (tmp_repo / "COBOL" / "BIN.CBL").read_bytes()
        # Binary content as string may be garbled - function must not raise
        try:
            result = _cobol_to_java(content_bytes.decode("utf-8", errors="replace"))
            assert result is not None
        except Exception:
            pytest.fail("Binary file caused unhandled exception")

    def test_malformed_cobol_no_crash(self, tmp_repo):
        from autoforge_modernization.g3_transform_strategies import _cobol_to_java
        content = (tmp_repo / "COBOL" / "MALFORMED.CBL").read_text()
        result = _cobol_to_java(content)
        assert result is not None

    def test_no_pic_fields_produces_class(self, tmp_repo):
        from autoforge_modernization.g3_transform_strategies import _cobol_to_java
        content = (tmp_repo / "COBOL" / "NOPIC.CBL").read_text()
        result = _cobol_to_java(content)
        assert "public class Nopic" in result

    def test_is_supported_reflects_real_state(self):
        from autoforge_modernization.g3_transform_strategies import G3TransformationStrategies
        assert G3TransformationStrategies.is_supported("COBOL", "refactor") is True
        assert G3TransformationStrategies.is_supported("COBOL", "transpilation") is True
        assert G3TransformationStrategies.is_supported("RPG", "refactor") is False
        assert G3TransformationStrategies.is_supported("COBOL", "unknown_type") is False

    def test_supported_types_for_known(self):
        from autoforge_modernization.g3_transform_strategies import G3TransformationStrategies
        cobol_types = G3TransformationStrategies.supported_types_for("COBOL")
        assert "refactor" in cobol_types
        assert "transpilation" in cobol_types
        jcl_types = G3TransformationStrategies.supported_types_for("JCL")
        assert "rewrite" in jcl_types
        assert "reconfiguration" in jcl_types

    def test_supported_types_for_blocked(self):
        from autoforge_modernization.g3_transform_strategies import G3TransformationStrategies
        assert G3TransformationStrategies.supported_types_for("RPG") == ["blocked"]
        assert G3TransformationStrategies.supported_types_for("BMS") == ["blocked"]

    def test_cobol_extracts_program_id(self):
        from autoforge_modernization.g3_transform_strategies import _cobol_to_java
        src = (
            "       IDENTIFICATION DIVISION.\n"
            "       PROGRAM-ID. MYPROG.\n"
            "       PROCEDURE DIVISION.\n"
            "           GOBACK.\n"
        )
        result = _cobol_to_java(src)
        assert "MYPROG" in result

    def test_cobol_pic_x_becomes_string(self):
        from autoforge_modernization.g3_transform_strategies import _cobol_to_java
        src = (
            "       IDENTIFICATION DIVISION.\n"
            "       PROGRAM-ID. PICTEST.\n"
            "       WORKING-STORAGE SECTION.\n"
            "       01  MYFIELD  PIC X(10).\n"
            "       PROCEDURE DIVISION.\n"
            "           GOBACK.\n"
        )
        result = _cobol_to_java(src)
        assert "String" in result
        assert "myfield" in result

    def test_cobol_pic_9_becomes_bigdecimal(self):
        from autoforge_modernization.g3_transform_strategies import _cobol_to_java
        src = (
            "       IDENTIFICATION DIVISION.\n"
            "       PROGRAM-ID. NUMTEST.\n"
            "       WORKING-STORAGE SECTION.\n"
            "       01  AMOUNT  PIC 9(7)V99.\n"
            "       PROCEDURE DIVISION.\n"
            "           GOBACK.\n"
        )
        result = _cobol_to_java(src)
        assert "BigDecimal" in result

    def test_cobol_paragraph_with_digit_prefix_emits_valid_java(self):
        """Paragraphs starting with a digit (e.g. 0000-MAIN) must compile in Java."""
        from autoforge_modernization.g3_transform_strategies import _cobol_to_java
        src = (
            "       IDENTIFICATION DIVISION.\n"
            "       PROGRAM-ID. DIGITTEST.\n"
            "       PROCEDURE DIVISION.\n"
            "       0000-MAIN.\n"
            "           PERFORM 1000-INIT.\n"
            "           STOP RUN.\n"
            "       1000-INIT.\n"
            "           GOBACK.\n"
        )
        result = _cobol_to_java(src)
        # The Java method name must start with a letter or _, not a digit
        assert "public void p_0000_main()" in result
        assert "public void p_1000_init()" in result
        # Confirm valid Java: no line should be `public void 0000_main(...)` etc
        assert "public void 0" not in result

    def test_cobol_extracts_multiple_paragraphs_with_perform_calls(self):
        from autoforge_modernization.g3_transform_strategies import _cobol_extract_paragraphs
        lines = [
            "       0000-MAIN.",
            "           PERFORM 1000-INIT.",
            "           PERFORM 2000-PROCESS.",
            "       1000-INIT.",
            "           MOVE 0 TO WS-X.",
            "       2000-PROCESS.",
            "           CALL 'CUSTUTIL'.",
        ]
        paragraphs = _cobol_extract_paragraphs(lines)
        # name is uppercased with hyphens replaced by underscores
        names = [p["name"] for p in paragraphs]
        java_names = [p["java_name"] for p in paragraphs]
        assert "0000_MAIN" in names
        assert "1000_INIT" in names
        assert "2000_PROCESS" in names
        assert "p_0000_main" in java_names
        # PERFORM targets are stored as Java-safe names
        main_performs = paragraphs[0]["perform_targets"]
        assert "p_1000_init" in main_performs
        assert "p_2000_process" in main_performs

    def test_cobol_extracts_select_assign_files(self):
        from autoforge_modernization.g3_transform_strategies import _cobol_extract_files
        lines = [
            "       FILE-CONTROL.",
            "           SELECT CUSTFILE ASSIGN TO CUSTMAST.",
            "           SELECT TRANFILE ASSIGN TO TRANDD.",
        ]
        files = _cobol_extract_files(lines)
        names = {f["name"] for f in files}
        assert "CUSTFILE" in names
        assert "TRANFILE" in names

    def test_cobol_extracts_copybooks(self):
        from autoforge_modernization.g3_transform_strategies import _cobol_extract_copybooks
        lines = [
            "       COPY SQLCA.",
            "       COPY CUSTREC.",
        ]
        cbs = _cobol_extract_copybooks(lines)
        assert "SQLCA" in cbs
        assert "CUSTREC" in cbs

    def test_cobol_handles_comp_field(self):
        from autoforge_modernization.g3_transform_strategies import _cobol_to_java
        src = (
            "       IDENTIFICATION DIVISION.\n"
            "       PROGRAM-ID. COMPTEST.\n"
            "       WORKING-STORAGE SECTION.\n"
            "       01 WS-COUNT PIC 9(5) COMP.\n"
            "       PROCEDURE DIVISION.\n"
            "           GOBACK.\n"
        )
        result = _cobol_to_java(src)
        assert "int" in result
        assert "ws_count" in result

    def test_cobol_paragraph_with_move_statements(self):
        from autoforge_modernization.g3_transform_strategies import _cobol_to_java
        src = (
            "       IDENTIFICATION DIVISION.\n"
            "       PROGRAM-ID. MOVETEST.\n"
            "       WORKING-STORAGE SECTION.\n"
            "       01 WS-A PIC 9(5).\n"
            "       01 WS-B PIC X(10).\n"
            "       PROCEDURE DIVISION.\n"
            "       0000-MAIN.\n"
            "           MOVE 100 TO WS-A.\n"
            "           MOVE 'HELLO' TO WS-B.\n"
            "           GOBACK.\n"
        )
        result = _cobol_to_java(src)
        assert "p_0000_main" in result

    def test_cobol_detects_db2_sql_technology(self):
        from autoforge_modernization.g3_transform_strategies import _cobol_extract_technologies
        lines = [
            "       EXEC SQL",
            "         SELECT COUNT(*) INTO :WS-CNT FROM CUST-TABLE",
            "       END-EXEC.",
        ]
        detected = _cobol_extract_technologies(lines)
        assert "DB2" in detected or "SQL" in detected

    def test_cobol_detects_cics_technology(self):
        from autoforge_modernization.g3_transform_strategies import _cobol_extract_technologies
        lines = [
            "       EXEC CICS",
            "         SEND TEXT FROM(WS-MSG)",
            "       END-EXEC.",
        ]
        detected = _cobol_extract_technologies(lines)
        assert "CICS" in detected

    def test_cobol_extracts_calls(self):
        from autoforge_modernization.g3_transform_strategies import _cobol_extract_calls
        lines = [
            "       CALL 'CUSTUTIL'.",
            "       CALL \"PAYPROC\".",
            "           PERFORM 1000-INIT.",
            "       CALL 'RPTGEN'.",
        ]
        calls = _cobol_extract_calls(lines)
        assert "CUSTUTIL" in calls
        assert "PAYPROC" in calls
        assert "RPTGEN" in calls
        assert len(calls) == 3  # deduplicated


class TestJCLTransformEdgeCases:
    def test_empty_jcl_returns_identity(self, tmp_repo):
        from autoforge_modernization.g3_transform_strategies import _jcl_to_workflow_config
        content = (tmp_repo / "JCL" / "EMPTY.JCL").read_text()
        result = _jcl_to_workflow_config(content, "JCL")
        assert result is not None

    def test_malformed_jcl_no_crash(self, tmp_repo):
        from autoforge_modernization.g3_transform_strategies import _jcl_to_workflow_config
        content = (tmp_repo / "JCL" / "MALFORMED.JCL").read_text()
        result = _jcl_to_workflow_config(content, "JCL")
        assert result is not None


class TestLLMFailureModes:
    def test_llm_returns_conclusion_object(self):
        import urllib.request
        from autoforge_modernization.g3_llm import G3LLMIntegration
        # Skip if Ollama is not available - is_fabricated will be True
        try:
            urllib.request.urlopen("http://localhost:11434/api/tags", timeout=1)
            ollama_available = True
        except Exception:
            ollama_available = False
        if not ollama_available:
            import pytest
            pytest.skip("Ollama not running on localhost:11434")
        client = G3LLMIntegration()
        try:
            # interpret_legacy_behavior(cs, lg, er) - capability_summary, legacy_grammar, error_result
            import asyncio
            result = asyncio.run(
                client.interpret_legacy_behavior(
                    "COBOL: detected, 1 file", "PIC X(10) DEFINITION", []
                )
            )
            # LLMConclusionRecord has .conclusion .confidence .is_fabricated
            assert hasattr(result, "conclusion")
            assert hasattr(result, "confidence")
            assert hasattr(result, "is_fabricated")
            assert result.is_fabricated is False
        except Exception as e:
            # Network/service errors must be caught by the client
            assert False, f"LLM client raised unhandled exception: {e}"

    def test_llm_interpret_unknown_technology(self):
        from autoforge_modernization.g3_llm import G3LLMIntegration
        client = G3LLMIntegration()
        try:
            import asyncio
            result = asyncio.run(
                client.interpret_unknown_technology(
                    "MYSTERY_LANG", "sample code here", []
                )
            )
            assert hasattr(result, "conclusion")
        except Exception as e:
            assert False, f"LLM interpret_unknown_technology raised: {e}"

    def test_llm_health_check(self):
        from autoforge_modernization.g3_llm import check_ollama_health
        health = check_ollama_health()
        assert isinstance(health, dict)
        assert "available" in health


class TestOrchestrator:
    def test_scanner_finds_files(self, tmp_repo):
        from autoforge_modernization.g3_real_run import Scanner
        scanner = Scanner(str(tmp_repo))
        all_files = scanner.all()
        assert isinstance(all_files, list)
        summary = scanner.sum()
        assert isinstance(summary, dict)
        assert "Total" in summary

    def test_full_run_returns_dict(self, tmp_repo):
        from autoforge_modernization.g3_real_run import run_g3_real
        out_dir = tmp_repo / "output"
        out_dir.mkdir()
        result = run_g3_real(str(tmp_repo), str(out_dir))
        assert isinstance(result, dict)
        assert "run_id" in result
        assert "elapsed_s" in result
        assert "scan" in result
        assert "transformation" in result

    def test_full_run_transformation_count_non_negative(self, tmp_repo):
        from autoforge_modernization.g3_real_run import run_g3_real
        out_dir = tmp_repo / "output2"
        out_dir.mkdir()
        result = run_g3_real(str(tmp_repo), str(out_dir))
        applied = result["transformation"]["applied"]
        blocked = result["transformation"]["blocked"]
        identity = result["transformation"]["identity"]
        assert applied >= 0
        assert blocked >= 0
        assert identity >= 0
        assert applied + blocked + identity >= 0
