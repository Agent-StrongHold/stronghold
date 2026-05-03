"""Stronghold error hierarchy.

Every domain-specific error carries a `code` for programmatic handling
and a `detail` for human consumption. Replaces scattered RuntimeError,
HTTPException, and ValueError from Conductor.
"""

from __future__ import annotations


class StrongholdError(Exception):
    """Base error for all Stronghold domain errors."""

    code: str = "STRONGHOLD_ERROR"

    def __init__(self, detail: str = "", *, code: str | None = None) -> None:
        self.detail = detail
        if code is not None:
            self.code = code
        super().__init__(f"[{self.code}] {detail}")


# ── Routing ──────────────────────────────────────────────────────


class RoutingError(StrongholdError):
    """Model routing failure."""

    code = "ROUTING_ERROR"


class QuotaReserveError(RoutingError):
    """All eligible models are in quota reserve."""

    code = "QUOTA_RESERVE_BLOCKED"


class QuotaExhaustedError(RoutingError):
    """All providers are at or above 100% quota usage."""

    code = "QUOTA_EXHAUSTED"


class NoModelsError(RoutingError):
    """No active models available for the request."""

    code = "NO_MODELS_AVAILABLE"


# ── Classification ───────────────────────────────────────────────


class ClassificationError(StrongholdError):
    """Intent classification failure."""

    code = "CLASSIFICATION_ERROR"


# ── Authentication & Authorization ───────────────────────────────


class AuthError(StrongholdError):
    """Authentication or authorization failure."""

    code = "AUTH_ERROR"


class TokenExpiredError(AuthError):
    """JWT token has expired."""

    code = "TOKEN_EXPIRED"


class PermissionDeniedError(AuthError):
    """User lacks permission for the requested action."""

    code = "PERMISSION_DENIED"


# ── Tool Execution ───────────────────────────────────────────────


class ToolError(StrongholdError):
    """Tool execution failure."""

    code = "TOOL_ERROR"


# ── Security ─────────────────────────────────────────────────────


class SecurityError(StrongholdError):
    """Security violation detected."""

    code = "SECURITY_ERROR"


class InjectionError(SecurityError):
    """Prompt injection detected."""

    code = "INJECTION_DETECTED"


class TrustViolationError(SecurityError):
    """Trust tier violation."""

    code = "TRUST_VIOLATION"


# ── Configuration ────────────────────────────────────────────────


class ConfigError(StrongholdError):
    """Configuration validation failure."""

    code = "CONFIG_ERROR"


# ── Skills ───────────────────────────────────────────────────────


class SkillError(StrongholdError):
    """Skill loading, parsing, or forge failure."""

    code = "SKILL_ERROR"


# ── Canvas Studio (Da Vinci design system) ──────────────────────


class CanvasStudioError(StrongholdError):
    """Base for canvas-studio (design system) errors.

    Distinct from `stronghold.types.canvas.CanvasError` which covers the
    operational canvas tool's runtime errors.
    """

    code = "CANVAS_STUDIO_ERROR"


class EffectKindUnknownError(CanvasStudioError):
    """Effect kind not registered in EffectKind enum."""

    code = "EFFECT_KIND_UNKNOWN"


class EffectParamsError(ConfigError):
    """Effect params failed schema validation."""

    code = "EFFECT_PARAMS_INVALID"


class EffectStackOverflowError(ConfigError):
    """Effect stack exceeded MAX_EFFECTS_PER_LAYER."""

    code = "EFFECT_STACK_OVERFLOW"


class MaskParamsError(ConfigError):
    """Mask params invalid for chosen MaskOrigin."""

    code = "MASK_PARAMS_INVALID"


class MaskBackendError(ToolError):
    """Mask-generation backend (rembg/SAM/etc.) failed."""

    code = "MASK_BACKEND_ERROR"


class MaskNotFoundError(CanvasStudioError):
    """Mask reference not found (load by name) or empty result from backend."""

    code = "MASK_NOT_FOUND"


class MaskDimensionMismatchError(ConfigError):
    """Mask dims do not match layer and auto_resize is disabled."""

    code = "MASK_DIM_MISMATCH"


class MaskOutOfBoundsError(ToolError):
    """Mask intersects layer bounds with zero area."""

    code = "MASK_OUT_OF_BOUNDS"


class GenerativeBackendError(RoutingError):
    """All generative endpoints failed in fallback chain."""

    code = "GENERATIVE_BACKEND_ERROR"


class UpscaleLimitError(ConfigError):
    """Upscale would exceed dimensional cap."""

    code = "UPSCALE_LIMIT"


class DocumentNotFoundError(CanvasStudioError):
    """Document id not found (or not visible to caller's tenant)."""

    code = "DOCUMENT_NOT_FOUND"


class EmptyDocumentError(CanvasStudioError):
    """Document has zero pages; export refused."""

    code = "EMPTY_DOCUMENT"


class ConcurrentEditError(CanvasStudioError):
    """Optimistic-lock conflict on a document mutation."""

    code = "CONCURRENT_EDIT"


class MasterInUseError(CanvasStudioError):
    """Master page deletion blocked because pages still reference it."""

    code = "MASTER_IN_USE"


class InvalidPageOrderingError(ConfigError):
    """Page ordering violates uniqueness/parity invariants."""

    code = "INVALID_PAGE_ORDERING"


class InvalidPageSizeError(ConfigError):
    """Page trim_size is non-finite or out-of-range."""

    code = "INVALID_PAGE_SIZE"


class DPILowError(ConfigError):
    """Layer's effective resolution is below the page's print DPI."""

    code = "DPI_LOW"


class BleedMissingError(ConfigError):
    """A page lacks a background that covers bleed."""

    code = "BLEED_MISSING"


class FontNotFoundError(SkillError):
    """Requested font family not registered or not in fallback chain."""

    code = "FONT_NOT_FOUND"


class FontValidationError(SecurityError):
    """Uploaded font failed table-whitelist validation."""

    code = "FONT_VALIDATION"


class FontNotEmbeddableError(SecurityError):
    """Font's embedding rights forbid PDF embedding."""

    code = "FONT_NOT_EMBEDDABLE"


class TextOnPathLengthError(ConfigError):
    """Text on path exceeds available path length without truncation policy."""

    code = "TEXT_ON_PATH_LENGTH"


class ShapeParamsError(ConfigError):
    """Shape geometry invalid (e.g. STAR with points<3, NaN coords)."""

    code = "SHAPE_PARAMS_INVALID"


class BooleanOpFailedError(ToolError):
    """Boolean path op failed (geometry library exception)."""

    code = "BOOLEAN_OP_FAILED"


class ConnectorAnchorError(ConfigError):
    """Invalid anchor reference on a connector shape."""

    code = "CONNECTOR_ANCHOR_INVALID"


class StyleLockNotFoundError(CanvasStudioError):
    code = "STYLE_LOCK_NOT_FOUND"


class StyleLockApplyConflictError(ConfigError):
    code = "STYLE_LOCK_APPLY_CONFLICT"


class StyleDriftCheckUnavailableError(RoutingError):
    code = "STYLE_DRIFT_UNAVAILABLE"


class TemplateNotFoundError(CanvasStudioError):
    code = "TEMPLATE_NOT_FOUND"


class TemplateApplyError(ConfigError):
    code = "TEMPLATE_APPLY_ERROR"


class TemplateTrustViolationError(SecurityError):
    code = "TEMPLATE_TRUST_VIOLATION"


class TemplatePromptTemplateError(ConfigError):
    code = "TEMPLATE_PROMPT_INVALID"


class TemplateAuthoringValidationError(ConfigError):
    code = "TEMPLATE_AUTHORING_INVALID"


class AssetNotFoundError(CanvasStudioError):
    code = "ASSET_NOT_FOUND"


class AssetUploadValidationError(SecurityError):
    code = "ASSET_UPLOAD_VALIDATION"


class AssetReferenceInUseError(ConfigError):
    code = "ASSET_REFERENCE_IN_USE"


class EmbeddingUnavailableError(RoutingError):
    code = "EMBEDDING_UNAVAILABLE"


class PreflightFailedError(ConfigError):
    code = "PREFLIGHT_FAILED"


class RuleNotFoundError(ConfigError):
    code = "PREFLIGHT_RULE_UNKNOWN"


class VersionNotFoundError(CanvasStudioError):
    code = "VERSION_NOT_FOUND"


class VersionTooOldError(CanvasStudioError):
    code = "VERSION_RETIRED"


class RevertConflictError(CanvasStudioError):
    code = "REVERT_CONFLICT"


class BudgetExceededError(QuotaExhaustedError):
    code = "BUDGET_EXCEEDED"


class ApprovalRequiredError(StrongholdError):
    """Cost gate requires user approval; not strictly an error."""

    code = "APPROVAL_REQUIRED"


class ForecastUnavailableError(RoutingError):
    code = "FORECAST_UNAVAILABLE"


class WizardSessionNotFoundError(CanvasStudioError):
    code = "WIZARD_SESSION_NOT_FOUND"


class WizardStepUnknownError(ConfigError):
    code = "WIZARD_STEP_UNKNOWN"


class WizardInputInvalidError(ConfigError):
    code = "WIZARD_INPUT_INVALID"


class AltTextRequiredError(SecurityError):
    code = "ALT_TEXT_REQUIRED"


class ContrastFailedError(ConfigError):
    code = "CONTRAST_FAILED"


class ChartSpecError(ConfigError):
    code = "CHART_SPEC_INVALID"


class ChartDataLoadError(ToolError):
    code = "CHART_DATA_LOAD"


class ChartRenderBackendError(ToolError):
    code = "CHART_RENDER_BACKEND"


class CSVInjectionError(SecurityError):
    code = "CSV_INJECTION"


class ExportFormatUnsupportedError(ConfigError):
    code = "EXPORT_FORMAT_UNSUPPORTED"


class ExportSizeError(ConfigError):
    code = "EXPORT_SIZE"


class ExportBackendError(ToolError):
    code = "EXPORT_BACKEND"


class SmartResizeTextOverflowError(ConfigError):
    code = "SMART_RESIZE_TEXT_OVERFLOW"


class SmartResizeTargetInvalidError(ConfigError):
    code = "SMART_RESIZE_TARGET_INVALID"


class SmartResizeBackendError(ToolError):
    code = "SMART_RESIZE_BACKEND"


class ManuscriptFormatUnsupportedError(ConfigError):
    code = "MANUSCRIPT_FORMAT_UNSUPPORTED"


class ManuscriptParseError(ToolError):
    code = "MANUSCRIPT_PARSE"


class ManuscriptStructureUnclearError(ConfigError):
    code = "MANUSCRIPT_STRUCTURE_UNCLEAR"


class ManuscriptEncodingError(ToolError):
    code = "MANUSCRIPT_ENCODING"


class LanguageUnsupportedError(ConfigError):
    code = "LANGUAGE_UNSUPPORTED"


class TranslationFailedError(RoutingError):
    code = "TRANSLATION_FAILED"


class LocalizationOverflowError(ConfigError):
    code = "LOCALIZATION_OVERFLOW"


class NarrationBackendError(RoutingError):
    code = "NARRATION_BACKEND"


class VoiceNotFoundError(ConfigError):
    code = "VOICE_NOT_FOUND"


class VoiceCloneRightsViolationError(SecurityError):
    code = "VOICE_CLONE_RIGHTS_VIOLATION"


class CorrectionStorageError(CanvasStudioError):
    code = "CORRECTION_STORAGE"


class IntentInferenceUnavailableError(RoutingError):
    code = "INTENT_INFERENCE_UNAVAILABLE"


class LearningStorageError(CanvasStudioError):
    code = "LEARNING_STORAGE"


class LearningContradictionUnresolvedError(CanvasStudioError):
    code = "LEARNING_CONTRADICTION_UNRESOLVED"


class CriticNotFoundError(CanvasStudioError):
    code = "CRITIC_NOT_FOUND"


class CriticConfigInvalidError(ConfigError):
    code = "CRITIC_CONFIG_INVALID"


class InsufficientTrainingDataError(ConfigError):
    code = "LORA_INSUFFICIENT_DATA"


class LoraTrainingFailedError(ToolError):
    code = "LORA_TRAINING_FAILED"


class LoraQualityGateFailedError(ConfigError):
    code = "LORA_QUALITY_GATE_FAILED"


class LoraIncompatibleBaseModelError(ConfigError):
    code = "LORA_INCOMPATIBLE_BASE"


class LoraTrainerUnavailableError(RoutingError):
    code = "LORA_TRAINER_UNAVAILABLE"
