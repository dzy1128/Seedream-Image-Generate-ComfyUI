import { app } from "../../scripts/app.js";

const CUSTOM_RESOLUTION_OPTION = "输入自定义分辨率...";
const DEFAULT_RESOLUTION = "2K";

function normalizeResolution(value) {
    return String(value || "").trim();
}

function ensureValueInOptions(widget, value) {
    if (!widget?.options || !Array.isArray(widget.options.values)) {
        return;
    }

    const normalized = normalizeResolution(value);
    if (!normalized || widget.options.values.includes(normalized)) {
        return;
    }

    const customIndex = widget.options.values.indexOf(CUSTOM_RESOLUTION_OPTION);
    if (customIndex >= 0) {
        widget.options.values.splice(customIndex, 0, normalized);
    } else {
        widget.options.values.push(normalized);
    }
}

app.registerExtension({
    name: "Seedream.ImageGenerateV2.EditableResolution",
    async beforeRegisterNodeDef(nodeType, nodeData) {
        if (nodeData?.name !== "SeedreamImageGenerateV2") {
            return;
        }

        const originalOnNodeCreated = nodeType.prototype.onNodeCreated;
        nodeType.prototype.onNodeCreated = function (...args) {
            const result = originalOnNodeCreated?.apply(this, args);
            const widget = this.widgets?.find((item) => item.name === "resolution");
            if (!widget) {
                return result;
            }

            ensureValueInOptions(widget, widget.value);
            const originalCallback = widget.callback;
            widget.callback = (value, canvas, node, pos, event) => {
                if (value === CUSTOM_RESOLUTION_OPTION) {
                    const currentValue = normalizeResolution(widget.value);
                    const entered = window.prompt("请输入自定义分辨率，例如 2560x1440", currentValue !== CUSTOM_RESOLUTION_OPTION ? currentValue : "");
                    const nextValue = normalizeResolution(entered) || DEFAULT_RESOLUTION;
                    ensureValueInOptions(widget, nextValue);
                    widget.value = nextValue;
                    this.setDirtyCanvas(true, true);

                    if (originalCallback) {
                        return originalCallback.call(widget, nextValue, canvas, node, pos, event);
                    }
                    return;
                }

                ensureValueInOptions(widget, value);
                return originalCallback?.call(widget, value, canvas, node, pos, event);
            };

            return result;
        };
    },
});
