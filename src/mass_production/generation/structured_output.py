"""Helpers for resilient structured Gemini text generation."""

from pathlib import Path
from typing import Callable, Optional, TypeVar

from clients.gemini_client import GeminiClient
from config import constants
from file_tools.io_utils import write_text
from file_tools.parsing import StructuredOutputParseError
from schedule.logger_config import log_action


ParsedType = TypeVar("ParsedType")


def build_retry_prompt(
    prompt: str,
    invalid_response: str,
    parse_error: str,
) -> str:
    """Build a retry prompt after structured-output parsing fails.

    Args:
        prompt: Original prompt.
        invalid_response: Previous invalid model response.
        parse_error: Parse error message.

    Returns:
        Prompt that asks Gemini to regenerate the same content as valid JSON only.
    """
    log_action("Building structured-output retry prompt")
    return (
        f"{prompt.strip()}\n\n"
        "The previous response was invalid JSON and could not be parsed.\n"
        f"Parsing error: {parse_error}\n"
        "Return the same response content again as valid JSON only.\n"
        "Do not wrap the JSON in markdown fences.\n"
        "Do not add commentary, numbering, or explanatory text.\n\n"
        "Previous invalid response:\n"
        f"{invalid_response.strip()}"
    )


def write_parse_failure_artifacts(
    output_dir: Optional[Path],
    artifact_stem: str,
    attempt_number: int,
    invalid_response: str,
    parse_error: str,
    retry_prompt: Optional[str] = None,
) -> None:
    """Persist malformed structured-output diagnostics to disk.

    Args:
        output_dir: Optional artifact directory.
        artifact_stem: Base file stem for artifacts.
        attempt_number: Attempt number that failed.
        invalid_response: Invalid model response text.
        parse_error: Parse failure message.
        retry_prompt: Optional follow-up prompt for the next attempt.
    """
    log_action("Writing structured-output parse failure artifacts")
    if output_dir is None:
        return

    suffix: str = f"{artifact_stem}_attempt_{attempt_number}"
    write_text(output_dir / f"{suffix}_response.txt", invalid_response)
    write_text(output_dir / f"{suffix}_parse_error.txt", parse_error)
    if retry_prompt is not None:
        write_text(output_dir / f"{suffix}_retry_prompt.txt", retry_prompt)


def generate_structured_output(
    gemini: GeminiClient,
    prompt: str,
    parser: Callable[[str], ParsedType],
    response_label: str,
    output_dir: Optional[Path] = None,
    artifact_stem: str = "structured_output",
    max_retries: int = constants.MAX_STRUCTURED_OUTPUT_RETRIES,
) -> ParsedType:
    """Generate Gemini text and parse it with content-format retries.

    Args:
        gemini: Gemini client.
        prompt: Base prompt text.
        parser: Parser for the expected structured output.
        response_label: Human-readable label for logging.
        output_dir: Optional artifact directory for malformed responses.
        artifact_stem: File stem for malformed-response artifacts.
        max_retries: Number of content-format retry attempts after the first call.

    Returns:
        Parsed structured payload.

    Raises:
        StructuredOutputParseError: If all attempts still produce malformed output.
    """
    log_action(f"Generating structured output for {response_label}")
    current_prompt: str = prompt
    total_attempts: int = max_retries + 1
    for attempt_number in range(1, total_attempts + 1):
        response_text: str = gemini.generate_text(current_prompt).strip()
        try:
            return parser(response_text)
        except StructuredOutputParseError as exc:
            log_action(
                f"Structured output parse failed for {response_label} on "
                f"attempt {attempt_number}/{total_attempts}: {exc}"
            )
            retry_prompt: Optional[str] = None
            if attempt_number < total_attempts:
                retry_prompt = build_retry_prompt(
                    prompt=prompt,
                    invalid_response=response_text,
                    parse_error=str(exc),
                )
            write_parse_failure_artifacts(
                output_dir=output_dir,
                artifact_stem=artifact_stem,
                attempt_number=attempt_number,
                invalid_response=response_text,
                parse_error=str(exc),
                retry_prompt=retry_prompt,
            )
            if retry_prompt is None:
                raise StructuredOutputParseError(
                    message=str(exc),
                    original_text=response_text,
                    candidate_text=exc.candidate_text,
                    repaired_text=exc.repaired_text,
                ) from exc
            current_prompt = retry_prompt

    raise StructuredOutputParseError(
        message=f"Failed to generate valid structured output for {response_label}",
        original_text="",
        candidate_text="",
    )
