using System;
using System.Collections.Generic;
using System.Windows.Media;
using System.Windows.Media.Imaging;

namespace HermesPet;

/// <summary>
/// Pet display state — maps Hermes agent state to visual properties.
/// Used by both DEBUG mode (text + color label) and PET mode (sprite + canvas).
/// </summary>
public class PetDisplayState
{
    public string HermesState { get; set; } = "unknown";
    public string SpeechText { get; set; } = "";
    public Color EmotionColor { get; set; } = Colors.Transparent;
    public bool ClickThrough { get; set; } = true;

    // DEBUG mode
    public string DebugLabel { get; set; } = "";

    // PET mode — frame info for the animation timer
    public PetFrame[] Frames { get; set; } = Array.Empty<PetFrame>();

    // PET mode — built-in renderer colors (per-pet theming)
    public Color PetBodyColor { get; set; } = Color.FromRgb(100, 180, 100);
    public Color PetAccentColor { get; set; } = Color.FromRgb(255, 255, 255);
    public Color PetEyeColor { get; set; } = Color.FromRgb(0, 0, 0);
}

/// <summary>
/// Maps Hermes agent states to visual display properties.
/// Works in two modes: DEBUG (text labels) and PET (sprite frames).
/// </summary>
public class PetEngine
{
    private static readonly Color[] StateColors = new Color[]
    {
        Color.FromRgb(60, 60, 60),       // idle
        Color.FromRgb(66, 133, 244),     // listening
        Colors.Orange,                   // thinking
        Color.FromRgb(52, 168, 83),      // tool_running
        Color.FromRgb(251, 188, 4),      // waiting_for_jack
        Color.FromRgb(52, 168, 83),      // done
        Colors.Red,                      // error
        Colors.Gray,                     // unknown
    };

    private static readonly string[] StateNames = new[]
    {
        "idle", "listening", "thinking", "tool_running",
        "waiting_for_jack", "done", "error", "unknown"
    };

    private static readonly string[] AccessoryText = new[]
    {
        "",       // idle
        "🎤",      // listening
        "🧠",      // thinking
        "⚙️",      // tool_running
        "❓",      // waiting_for_jack
        "✅",      // done
        "⚠️",      // error
        "…",       // unknown
    };

    public PetAssetManager AssetManager { get; } = new PetAssetManager();

    /// <summary>Current known state string.</summary>
    public string? CurrentState { get; private set; }

    /// <summary>Whether we are in PET mode (vs DEBUG mode).</summary>
    public bool PetMode { get; set; } = true;

    /// <summary>Whether to overlay a small debug label on PET mode.</summary>
    public bool ShowDebugLabel { get; set; } = false;

    /// <summary>Initialize and try to load the named pet.</summary>
    public bool LoadPet(string petName = "border-collie-v2")
    {
        return AssetManager.LoadPet(petName);
    }

    /// <summary>
    /// Map Hermes state to a display state.
    /// </summary>
    public PetDisplayState MapState(string state, Dictionary<string, object>? payload)
    {
        CurrentState = state;
        int idx = Array.IndexOf(StateNames, state);
        if (idx < 0) idx = 7;

        var display = new PetDisplayState
        {
            HermesState = state,
            EmotionColor = StateColors[idx],
            ClickThrough = state is "idle" or "done" or "unknown",
            DebugLabel = $"State: {state}",
            PetBodyColor = GetPetBodyColor(),
            PetAccentColor = GetPetAccentColor(),
            PetEyeColor = GetPetEyeColor(),
        };

        // Speech text for both modes
        display.SpeechText = GetSpeechForState(state, payload);

        // PET mode: load animation frames
        if (PetMode)
        {
            display.Frames = AssetManager.GetFramesForState(state);
            // If no frames from the asset manager, use built-in shape rendering
            if (display.Frames.Length == 0)
            {
                // Built-in: create placeholders (drawn in the canvas)
                display.Frames = GetBuiltinFramesForState(state);
            }
        }

        return display;
    }

    /// <summary>Built-in frames — rendered as colored shapes on the WPF canvas.</summary>
    private static PetFrame[] GetBuiltinFramesForState(string state)
    {
        int idx = Array.IndexOf(StateNames, state);
        if (idx < 0) idx = 7;

        // Return frame metadata — the canvas renderer uses these shapes
        return new[]
        {
            new PetFrame
            {
                Index = idx,
                Source = null,
                DurationMs = 500,
            }
        };
    }

    private static string GetSpeechForState(string state, Dictionary<string, object>? payload)
    {
        return state switch
        {
            "idle" => "",
            "listening" => "Listening...",
            "thinking" => payload?.TryGetValue("message_preview", out var preview) == true
                ? preview?.ToString() ?? "Thinking..."
                : "Thinking...",
            "tool_running" => payload?.TryGetValue("tool_name", out var tool) == true
                ? $"{tool}..."
                : "Running...",
            "waiting_for_jack" => "Waiting for you...",
            "done" => "Done!",
            "error" => "Something went wrong",
            "unknown" => "...",
            _ => "",
        };
    }

    // ── Per-pet color theming ────────────────────

    private Color GetPetBodyColor()
    {
        return AssetManager.CurrentPet switch
        {
            "border-collie" or "border-collie-v2" => Color.FromRgb(30, 30, 30),    // black body
            _ => Color.FromRgb(100, 180, 100),               // default green
        };
    }

    private Color GetPetAccentColor()
    {
        return AssetManager.CurrentPet switch
        {
            "border-collie" or "border-collie-v2" => Color.FromRgb(255, 255, 255), // white accents
            _ => Color.FromRgb(255, 255, 255),               // default white
        };
    }

    private Color GetPetEyeColor()
    {
        return AssetManager.CurrentPet switch
        {
            "border-collie" or "border-collie-v2" => Color.FromRgb(139, 90, 43),   // brown eyes
            _ => Color.FromRgb(0, 0, 0),                      // default black
        };
    }
}
