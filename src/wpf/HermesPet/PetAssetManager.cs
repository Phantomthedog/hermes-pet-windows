using System;
using System.Collections.Generic;
using System.IO;
using System.Text.Json;
using System.Text.Json.Serialization;
using System.Windows.Media;
using System.Windows.Media.Imaging;

namespace HermesPet;

/// <summary>
/// Describes a single pet's animation state mapping.
/// </summary>
public class PetStateAnimation
{
    [JsonPropertyName("frames")]
    public int[] Frames { get; set; } = Array.Empty<int>();

    [JsonPropertyName("frame_ms")]
    public int FrameMs { get; set; } = 300;

    [JsonPropertyName("loop")]
    public bool Loop { get; set; } = true;
}

/// <summary>
/// Describes one animation frame (sprite source + optional metadata).
/// </summary>
public class PetFrame
{
    public int Index { get; set; }
    public ImageSource? Source { get; set; }
    public int DurationMs { get; set; } = 300;
    public bool Loop { get; set; } = true;
}

/// <summary>
/// Loads and manages pet sprite assets from the assets/pets/ directory.
/// Supports both external sprite sheets and built-in rendering.
/// </summary>
public class PetAssetManager
{
    private readonly string _assetsDir;
    private string _currentPet = "border-collie-v2";
    private Dictionary<string, PetStateAnimation> _stateAnimations = new();
    private List<ImageSource> _frames = new();
    private bool _loaded;

    public PetAssetManager()
    {
        // Walk up from the EXE directory until we find assets/pets/
        _assetsDir = FindAssetsDir();

        // Last resort fallback
        if (!Directory.Exists(_assetsDir))
        {
            _assetsDir = System.IO.Path.Combine(
                AppDomain.CurrentDomain.BaseDirectory, "assets\\pets"
            );
        }
    }

    /// <summary>Walk up from the exe directory to find assets/pets/.</summary>
    private static string FindAssetsDir()
    {
        var dir = new DirectoryInfo(AppDomain.CurrentDomain.BaseDirectory);
        while (dir != null)
        {
            var candidate = System.IO.Path.Combine(dir.FullName, "assets", "pets");
            if (Directory.Exists(candidate))
                return candidate;
            dir = dir.Parent;
        }
        return System.IO.Path.Combine(
            AppDomain.CurrentDomain.BaseDirectory, "..\\..\\..\\..\\..\\..\\assets\\pets"
        );
    }

    /// <summary>List all available pet directories.</summary>
    public string[] ListAvailablePets()
    {
        if (!Directory.Exists(_assetsDir))
            return Array.Empty<string>();

        try
        {
            var dirs = Directory.GetDirectories(_assetsDir)
                .Select(Path.GetFileName)
                .Where(name => name != null && name.Length > 0)
                .Select(name => name!)
                .OrderBy(n => n)
                .ToArray();
            return dirs;
        }
        catch
        {
            return Array.Empty<string>();
        }
    }

    /// <summary>Current pet name.</summary>
    public string CurrentPet => _currentPet;

    /// <summary>Whether sprite frames are loaded.</summary>
    public bool HasSprites => _loaded && _frames.Count > 0;

    /// <summary>Load a pet by name. Returns false if the pet cannot be loaded.</summary>
    public bool LoadPet(string petName)
    {
        _loaded = false;
        _frames.Clear();
        _stateAnimations.Clear();
        _currentPet = petName;

        // Find pet directory
        string petDir = System.IO.Path.Combine(_assetsDir, petName);
        if (!Directory.Exists(petDir))
        {
            System.Diagnostics.Debug.WriteLine($"Pet directory not found: {petDir}");
            return false;
        }

        // Read pet.json
        string manifestPath = System.IO.Path.Combine(petDir, "pet.json");
        if (!File.Exists(manifestPath))
        {
            System.Diagnostics.Debug.WriteLine($"pet.json not found in {petDir}");
            return false;
        }

        try
        {
            string json = File.ReadAllText(manifestPath);
            var manifest = JsonSerializer.Deserialize<PetManifest>(json);
            if (manifest == null) return false;

            _stateAnimations = manifest.States ?? new();

            // Load spritesheet if present
            string spritesheetPath = System.IO.Path.Combine(petDir, "spritesheet.png");
            if (File.Exists(spritesheetPath))
            {
                // Must use OnLoad cache option so BitmapImage loads synchronously
                // Otherwise PixelWidth/PixelHeight are 0 and CroppedBitmap fails
                var bitmap = new BitmapImage();
                bitmap.BeginInit();
                bitmap.CacheOption = BitmapCacheOption.OnLoad;
                bitmap.UriSource = new Uri(spritesheetPath, UriKind.Absolute);
                bitmap.EndInit();
                bitmap.Freeze(); // Make it cross-thread accessible

                int cellW = manifest.CellWidth > 0 ? manifest.CellWidth : 84;
                int cellH = manifest.CellHeight > 0 ? manifest.CellHeight : 84;

                int cols = bitmap.PixelWidth / cellW;
                int rows = bitmap.PixelHeight / cellH;
                int totalFrames = cols * rows;

                for (int i = 0; i < totalFrames; i++)
                {
                    int row = i / cols;
                    int col = i % cols;
                    var srcRect = new System.Windows.Int32Rect(col * cellW, row * cellH, cellW, cellH);
                    var cropped = new CroppedBitmap(bitmap, srcRect);
                    cropped.Freeze();
                    _frames.Add(cropped);
                }
            }

            _loaded = true;
            return true;
        }
        catch (Exception ex)
        {
            System.Diagnostics.Debug.WriteLine($"Failed to load pet {petName}: {ex.Message}");
            return false;
        }
    }

    /// <summary>
    /// Get the animation frames for a given Hermes state.
    /// Returns empty array if the state is not defined.
    /// </summary>
    public PetFrame[] GetFramesForState(string state)
    {
        if (!_stateAnimations.TryGetValue(state, out var anim))
        {
            // Try fallback to idle
            if (!_stateAnimations.TryGetValue("idle", out anim))
                return Array.Empty<PetFrame>();
        }

        var result = new List<PetFrame>();
        foreach (int frameIdx in anim.Frames)
        {
            ImageSource? src = null;
            if (frameIdx >= 0 && frameIdx < _frames.Count)
                src = _frames[frameIdx];

            result.Add(new PetFrame
            {
                Index = frameIdx,
                Source = src,
                DurationMs = anim.FrameMs,
                Loop = anim.Loop,
            });
        }
        return result.ToArray();
    }
}

/// <summary>JSON deserialization target for pet.json.</summary>
public class PetManifest
{
    [JsonPropertyName("name")]
    public string Name { get; set; } = "";

    [JsonPropertyName("display_name")]
    public string DisplayName { get; set; } = "";

    [JsonPropertyName("version")]
    public int Version { get; set; } = 1;

    [JsonPropertyName("cell_width")]
    public int CellWidth { get; set; } = 84;

    [JsonPropertyName("cell_height")]
    public int CellHeight { get; set; } = 84;

    [JsonPropertyName("frame_rate")]
    public int FrameRate { get; set; } = 8;

    [JsonPropertyName("states")]
    public Dictionary<string, PetStateAnimation>? States { get; set; }

    [JsonPropertyName("description")]
    public string Description { get; set; } = "";
}
