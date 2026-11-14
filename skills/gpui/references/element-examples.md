# Element Implementation Examples

## Simple Text Element

A complete custom element that delegates text shaping to `StyledText`, retains
it between rendering phases, and installs a text cursor over its hitbox. Often
`StyledText` alone is sufficient; this wrapper demonstrates the `Element`
lifecycle when custom interaction is needed.

The implementation and the headless draw test below are extracted by the source
repository's `validation/gpui/check.py` and checked against Zed
revision `4c7244790a075e862eeb4e5ccc12d6c8f5da6f7e`.
Highlight ranges are UTF-8 byte offsets: supply sorted, non-overlapping ranges
within the string and on character boundaries.

<!-- gpui-check: simple-text -->
```rust
use gpui::{
    App, Bounds, CursorStyle, Element, ElementId, GlobalElementId, HighlightStyle,
    Hitbox, HitboxBehavior, InspectorElementId, IntoElement, LayoutId, Pixels,
    SharedString, StyledText, Window,
};
use std::ops::Range;

pub struct SimpleText {
    id: ElementId,
    text: SharedString,
    highlights: Vec<(Range<usize>, HighlightStyle)>,
}

impl IntoElement for SimpleText {
    type Element = Self;

    fn into_element(self) -> Self::Element {
        self
    }
}

impl Element for SimpleText {
    type RequestLayoutState = StyledText;
    type PrepaintState = Hitbox;

    fn id(&self) -> Option<ElementId> {
        Some(self.id.clone())
    }

    fn source_location(&self) -> Option<&'static std::panic::Location<'static>> {
        None
    }

    fn request_layout(
        &mut self,
        global_id: Option<&GlobalElementId>,
        inspector_id: Option<&InspectorElementId>,
        window: &mut Window,
        cx: &mut App
    ) -> (LayoutId, Self::RequestLayoutState) {
        // Create styled text with highlights
        let mut runs = Vec::new();
        let mut ix = 0;

        for (range, highlight) in &self.highlights {
            // Add unstyled text before highlight
            if ix < range.start {
                runs.push(window.text_style().to_run(range.start - ix));
            }

            // Add highlighted text
            runs.push(
                window.text_style()
                    .highlight(*highlight)
                    .to_run(range.len())
            );
            ix = range.end;
        }

        // Add remaining unstyled text
        if ix < self.text.len() {
            runs.push(window.text_style().to_run(self.text.len() - ix));
        }

        let mut styled_text = StyledText::new(self.text.clone()).with_runs(runs);
        let (layout_id, _) = styled_text.request_layout(
            global_id,
            inspector_id,
            window,
            cx
        );

        (layout_id, styled_text)
    }

    fn prepaint(
        &mut self,
        global_id: Option<&GlobalElementId>,
        inspector_id: Option<&InspectorElementId>,
        bounds: Bounds<Pixels>,
        styled_text: &mut Self::RequestLayoutState,
        window: &mut Window,
        cx: &mut App
    ) -> Self::PrepaintState {
        // Prepaint the styled text
        styled_text.prepaint(
            global_id,
            inspector_id,
            bounds,
            &mut (),
            window,
            cx
        );

        // Create hitbox for interaction
        window.insert_hitbox(bounds, HitboxBehavior::Normal)
    }

    fn paint(
        &mut self,
        global_id: Option<&GlobalElementId>,
        inspector_id: Option<&InspectorElementId>,
        bounds: Bounds<Pixels>,
        styled_text: &mut Self::RequestLayoutState,
        hitbox: &mut Self::PrepaintState,
        window: &mut Window,
        cx: &mut App
    ) {
        // Paint the styled text
        styled_text.paint(
            global_id,
            inspector_id,
            bounds,
            &mut (),
            &mut (),
            window,
            cx
        );

        // Set cursor style for text
        window.set_cursor_style(CursorStyle::IBeam, hitbox);
    }
}
```

## Testing the rendering phases

`VisualTestContext::draw` runs layout, prepaint, and paint in their proper frame
phases. A raw `request_layout` call only registers layout work; it is not enough
to assert final geometry. Place this test beside `SimpleText` in a consumer with
GPUI's `test-support` feature enabled.

<!-- gpui-check: simple-text-test -->
```rust
#[cfg(test)]
mod tests {
    use super::SimpleText;
    use gpui::{Empty, HighlightStyle, TestAppContext, VisualTestContext, point, px, rgb, size};

    #[gpui::test]
    fn text_layout_and_hitbox_agree(cx: &mut TestAppContext) {
        let window = cx.add_window(|_, _| Empty);
        let mut cx = VisualTestContext::from_window(window.into(), cx);

        for (text, range) in [("fn main()", 0..2), ("éclair", 0..2)] {
            let origin = point(px(12.), px(18.));
            let (styled_text, hitbox) = cx.draw(origin, size(px(300.), px(80.)), |_, _| {
                SimpleText {
                    id: "sample-text".into(),
                    text: text.into(),
                    highlights: vec![(range, HighlightStyle {
                        color: Some(rgb(0xc586c0).into()),
                        ..Default::default()
                    })],
                }
            });

            let layout = styled_text.layout();
            assert_eq!(layout.text(), text);
            assert_eq!(layout.len(), text.len());
            assert_eq!(layout.bounds(), hitbox.bounds);
            assert_eq!(hitbox.bounds.origin, origin);
            assert!(hitbox.bounds.size.width > px(0.));
            assert!(hitbox.bounds.size.height > px(0.));
        }
    }
}
```

This checks text layout and hitbox placement, not native cursor appearance or
pixel output. Inspect those in a visible app when changing rendering or input.

## Interactive Element with Selection

Extend the complete example only when a higher-level text component is
insufficient. Keep selection in an owning entity, clone that entity into the
`'static` mouse handlers registered during paint, and notify it after mutation.
Do not capture the element's borrowed `&mut self` in a stored handler.

Use `TextLayout::index_for_position` and `position_for_index` at the pinned
revision to map between pointer positions and UTF-8 byte indices. Handle positions
outside the text and empty/reversed selections. Selection rectangles must be
computed from the actual shaped lines; `TextLayout` has no `rects_for_range` API
at the checked revision. Test dragging across lines, Unicode boundaries, and
clipping through real event dispatch before treating the component as complete.

## Complex Element with Child Management

Store heterogeneous children as `Vec<AnyElement>`. Their erased wrapper manages
the concrete children's layout and prepaint state:

- During layout, `child.request_layout(window, cx)` returns a `LayoutId`, not a tuple.
  Pass those IDs to the parent's layout request.
- During prepaint, use the computed layout bounds. `child.prepaint(window, cx)`
  uses the normal layout position; `prepaint_at(origin, window, cx)` supplies an
  explicit absolute origin for manual positioning.
- During paint, call `child.paint(window, cx)` without passing bounds again.

Scope clipping and scrolling consistently around prepaint and paint so hitboxes
match visible content. Prefer built-in containers and virtual lists when they
already implement the required layout. The broader
[patterns](element-patterns.md) and [advanced designs](element-advanced.md) are
illustrative sketches, not additional compiled implementations.
