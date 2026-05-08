"""Canvas Book Pipeline tool — end-to-end personalized book generation.

Exposes the MCP pipeline (character sheet, story, illustrations, PDF)
as a Stronghold tool that agents can call. Actions:
  - create_book: full pipeline (photo → character → story → illustrations → PDF)
  - create_character: photo → character features + reference sheet
  - create_story: character features → 32-page story
  - create_storyboard: structured scene decomposition with style contracts
  - generate_illustration: single page illustration
  - remove_bg: background removal from an image
"""

from __future__ import annotations

import base64
import io
import logging
import tempfile
from pathlib import Path
from typing import Any

from stronghold.types.tool import ToolDefinition, ToolResult

logger = logging.getLogger("stronghold.tools.canvas_book")

CANVAS_BOOK_TOOL_DEF = ToolDefinition(
    name="canvas_book",
    description=(
        "Personalized children's book creation pipeline. Generate character sheets, "
        "stories, illustrations, and print-ready PDFs. Actions: create_book (full pipeline), "
        "create_character (photo analysis), create_story (32-page story), "
        "create_storyboard (structured scene decomposition), generate_illustration "
        "(single page), remove_bg (background removal)."
    ),
    parameters={
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": [
                    "create_book",
                    "create_character",
                    "create_story",
                    "create_storyboard",
                    "generate_illustration",
                    "remove_bg",
                ],
                "description": "The book pipeline action to execute.",
            },
            "child_name": {
                "type": "string",
                "description": "Child's name for personalization.",
            },
            "child_age": {
                "type": "integer",
                "description": "Child's age (1-12).",
            },
            "photo_b64": {
                "type": "string",
                "description": "Base64-encoded photo of the child (for create_character/create_book).",
            },
            "book_type": {
                "type": "string",
                "enum": ["picture", "coloring-standard", "coloring-premium"],
                "description": "Type of book to create.",
            },
            "art_style": {
                "type": "string",
                "enum": ["warm watercolor", "bold_simple", "detailed_ornate"],
                "description": "Art style for illustrations.",
            },
            "interests": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Child's interests to incorporate (max 5).",
            },
            "theme_hint": {
                "type": "string",
                "description": "Theme or story direction hint.",
            },
            "image_b64": {
                "type": "string",
                "description": "Base64-encoded image (for remove_bg action).",
            },
            "prompt": {
                "type": "string",
                "description": "Illustration prompt (for generate_illustration action).",
            },
            "page_count": {
                "type": "integer",
                "description": "Number of scenes for storyboard (default 12).",
            },
            "orientation": {
                "type": "string",
                "enum": ["landscape (wide)", "portrait (tall)", "square"],
                "description": "Page orientation.",
            },
        },
        "required": ["action"],
    },
    groups=("creative", "canvas"),
)


class CanvasBookExecutor:
    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        action = arguments.get("action", "")
        try:
            if action == "create_book":
                return await self._create_book(arguments)
            if action == "create_character":
                return await self._create_character(arguments)
            if action == "create_story":
                return await self._create_story(arguments)
            if action == "create_storyboard":
                return await self._create_storyboard(arguments)
            if action == "generate_illustration":
                return await self._generate_illustration(arguments)
            if action == "remove_bg":
                return await self._remove_bg(arguments)
            return ToolResult(success=False, error=f"Unknown action: {action}")
        except Exception as e:
            logger.error("canvas_book action %s failed: %s", action, e)
            return ToolResult(success=False, error=str(e))

    async def _create_book(self, args: dict[str, Any]) -> ToolResult:
        from PIL import Image as PILImage

        child_name = args.get("child_name", "Friend")
        child_age = args.get("child_age", 5)
        book_type = args.get("book_type", "picture")
        art_style = args.get("art_style", "warm watercolor")
        photo_b64 = args.get("photo_b64", "")
        interests = args.get("interests", [])
        theme_hint = args.get("theme_hint", "")

        import json

        if not photo_b64:
            from stronghold.tools.canvas_book import CanvasBookExecutor

            return ToolResult(
                success=False,
                error="photo_b64 is required for create_book action",
            )

        with tempfile.TemporaryDirectory() as tmp:
            photo_path = Path(tmp) / "photo.png"
            img_data = base64.b64decode(photo_b64)
            PILImage.open(io.BytesIO(img_data)).save(photo_path)

            from canvas_studio_poc.server.mcp.pipeline import OrderSpec, run_pipeline

            order = OrderSpec(
                child_photo_path=str(photo_path),
                child_name=child_name,
                child_age=child_age,
                book_type=book_type,
                art_style=art_style,
                interests=interests,
                theme_hint=theme_hint,
            )

            result = run_pipeline(order, tmp, fallback_to_golden=True)

            summary = {
                "success": result.success,
                "stages_completed": result.stages_completed,
                "errors": result.errors,
                "product": result.product.name,
                "interior_pdf_size": result.interior_pdf_path.stat().st_size
                if result.interior_pdf_path.exists()
                else 0,
                "cover_pdf_size": result.cover_pdf_path.stat().st_size
                if result.cover_pdf_path.exists()
                else 0,
                "illustration_count": len(result.illustrations),
            }

            return ToolResult(
                success=result.success,
                content=json.dumps(summary),
            )

    async def _create_character(self, args: dict[str, Any]) -> ToolResult:
        import json

        from PIL import Image as PILImage

        photo_b64 = args.get("photo_b64", "")
        child_name = args.get("child_name", "Friend")
        child_age = args.get("child_age", 5)
        art_style = args.get("art_style", "warm watercolor")

        if not photo_b64:
            return ToolResult(success=False, error="photo_b64 is required")

        img_data = base64.b64decode(photo_b64)
        img = PILImage.open(io.BytesIO(img_data))

        from canvas_studio_poc.server.mcp.feature_extractor import extract_features
        from canvas_studio_poc.server.mcp.character import analyze_photo

        features = analyze_photo(img)
        local_features = extract_features(img)

        result = {
            "name": child_name,
            "age": child_age,
            "ai_features": {
                "hair": features.hair,
                "skin_tone": features.skin_tone,
                "eye_color": features.eye_color,
                "face_shape": features.face_shape,
                "signature_features": list(features.signature_features),
                "typical_expression": features.typical_expression,
            },
            "local_features": {
                "hair_color": local_features.hair_color,
                "skin_tone": local_features.skin_tone,
                "eye_color": local_features.eye_color,
                "description": local_features.description,
            },
        }

        return ToolResult(
            success=True,
            content=json.dumps(result),
        )

    async def _create_story(self, args: dict[str, Any]) -> ToolResult:
        import json

        child_name = args.get("child_name", "Friend")
        child_age = args.get("child_age", 5)
        theme_hint = args.get("theme_hint", "")

        from canvas_studio_poc.server.mcp.character import CharacterFeatures
        from canvas_studio_poc.server.mcp.story import generate_story, validate_story

        features = CharacterFeatures(
            hair=args.get("hair", "brown"),
            skin_tone=args.get("skin_tone", "medium"),
            eye_color=args.get("eye_color", "brown"),
            face_shape=args.get("face_shape", "round"),
            age_style=f"{child_age} years old",
            body_type="average build",
            signature_features=("bright smile",),
            typical_expression="cheerful",
        )

        story = generate_story(
            child_name=child_name,
            child_age=child_age,
            features=features,
            interests=args.get("interests", []),
            theme_hint=theme_hint,
        )
        issues = validate_story(story, child_age)

        result = {
            "title": story.title,
            "subtitle": story.subtitle,
            "dedication": story.dedication,
            "page_count": story.page_count,
            "pages": [
                {
                    "page_number": p.page_number,
                    "scene_type": p.scene_type,
                    "text": p.text[:100],
                    "illustration_prompt": p.illustration_prompt[:100],
                    "character_pose": p.character_pose,
                    "mood": p.mood,
                }
                for p in story.pages
            ],
            "validation_issues": issues,
        }

        return ToolResult(
            success=True,
            content=json.dumps(result),
        )

    async def _create_storyboard(self, args: dict[str, Any]) -> ToolResult:
        import json

        child_name = args.get("child_name", "Friend")
        child_age = args.get("child_age", 5)
        page_count = args.get("page_count", 12)
        orientation = args.get("orientation", "landscape (wide)")

        from canvas_studio_poc.server.mcp.character import CharacterFeatures
        from canvas_studio_poc.server.mcp.story import decompose_book

        features = CharacterFeatures(
            hair=args.get("hair", "brown"),
            skin_tone=args.get("skin_tone", "medium"),
            eye_color=args.get("eye_color", "brown"),
            face_shape=args.get("face_shape", "round"),
            age_style=f"{child_age} years old",
            body_type="average build",
            signature_features=("bright smile",),
            typical_expression="cheerful",
        )

        decomposition = decompose_book(
            child_name=child_name,
            child_age=child_age,
            features=features,
            page_count=page_count,
            orientation=orientation,
            theme=args.get("theme_hint", ""),
        )

        result = {
            "title": decomposition.title,
            "dedication": decomposition.dedication,
            "style_contract": {
                "art_style": decomposition.style_contract.art_style,
                "color_palette": list(decomposition.style_contract.color_palette),
                "lighting": decomposition.style_contract.lighting,
                "mood": decomposition.style_contract.mood,
                "recurring_elements": list(decomposition.style_contract.recurring_elements),
            },
            "scene_count": len(decomposition.scenes),
            "scenes": [
                {
                    "id": s.id,
                    "title": s.title,
                    "scene_type": s.scene_type,
                    "page_text": s.page_text[:100],
                    "pose": s.pose,
                    "composition": s.composition,
                    "character_action": s.character_action,
                    "prop_count": len(s.props),
                }
                for s in decomposition.scenes
            ],
        }

        return ToolResult(
            success=True,
            content=json.dumps(result),
        )

    async def _generate_illustration(self, args: dict[str, Any]) -> ToolResult:
        import json

        prompt = args.get("prompt", "")
        if not prompt:
            return ToolResult(success=False, error="prompt is required")

        from canvas_studio_poc.server.mcp.image_provider import generate_image

        img = generate_image(prompt)
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        b64 = base64.b64encode(buf.getvalue()).decode()

        return ToolResult(
            success=True,
            content=json.dumps(
                {
                    "image_b64": b64[:200] + "...",
                    "width": img.width,
                    "height": img.height,
                    "full_size_bytes": len(b64),
                }
            ),
        )

    async def _remove_bg(self, args: dict[str, Any]) -> ToolResult:
        import json

        from PIL import Image as PILImage

        image_b64 = args.get("image_b64", "")
        if not image_b64:
            return ToolResult(success=False, error="image_b64 is required")

        from canvas_studio_poc.server.mcp.bg_removal import remove_background

        img_data = base64.b64decode(image_b64)
        img = PILImage.open(io.BytesIO(img_data))
        result = remove_background(img)

        buf = io.BytesIO()
        result.save(buf, format="PNG")
        b64 = base64.b64encode(buf.getvalue()).decode()

        return ToolResult(
            success=True,
            content=json.dumps(
                {
                    "image_b64": b64[:200] + "...",
                    "width": result.width,
                    "height": result.height,
                    "full_size_bytes": len(b64),
                }
            ),
        )
