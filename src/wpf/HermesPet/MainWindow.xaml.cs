using System;
using System.Collections.Generic;
using System.ComponentModel;
using System.Threading;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Input;
using System.Windows.Media;
using System.Windows.Shapes;
using System.Windows.Threading;

namespace HermesPet;

/// <summary>
/// Main window for Hermes Pet — supports PET mode (character rendering)
/// and DEBUG mode (text labels). Right-click to switch modes, toggle labels,
/// reload assets, exit.
/// </summary>
public partial class MainWindow : Window
{
    private readonly PetEngine _engine;
    private readonly EventReceiver _receiver;
    private readonly Thread _receiverThread;
    private int _eventCount;
    private bool _petMode = true;
    private bool _debugLabelVisible = true;

    // Animation state
    private DispatcherTimer? _animTimer;
    private PetFrame[] _currentFrames = Array.Empty<PetFrame>();
    private int _currentFrameIndex;

    // Built-in pet face rendering data
    private static readonly Brush[] FaceColors = new Brush[]
    {
        new SolidColorBrush(Color.FromRgb(100, 180, 100)),  // idle — green
        new SolidColorBrush(Color.FromRgb(70, 140, 220)),   // listening — blue
        new SolidColorBrush(Color.FromRgb(220, 160, 60)),   // thinking — orange
        new SolidColorBrush(Color.FromRgb(80, 180, 80)),    // tool_running — green
        new SolidColorBrush(Color.FromRgb(200, 180, 50)),   // waiting_for_jack — yellow
        new SolidColorBrush(Color.FromRgb(80, 200, 100)),   // done — bright green
        new SolidColorBrush(Color.FromRgb(200, 60, 60)),    // error — red
        new SolidColorBrush(Color.FromRgb(130, 130, 130)),  // unknown — gray
    };

    private static readonly string[] StateNames = new[]
    {
        "idle", "listening", "thinking", "tool_running",
        "waiting_for_jack", "done", "error", "unknown"
    };

    // Bridge supervisor
    private readonly BridgeSupervisor? _bridgeSupervisor;
    private readonly DispatcherTimer _connectionTimer;
    private bool _manageBridge;

    public MainWindow(int port, double? initialX, double? initialY, bool manageBridge = true)
    {
        InitializeComponent();

        if (initialX.HasValue) Left = initialX.Value;
        if (initialY.HasValue) Top = initialY.Value;

        _engine = new PetEngine();

        // Try to load border-collie-v2; PET mode by default
        _engine.LoadPet("border-collie-v2");
        _engine.PetMode = true;
        _petMode = true;

        UpdateModeVisibility();

        // Setup animation timer BEFORE UpdateDisplay so StartAnimation() works
        _animTimer = new DispatcherTimer
        {
            Interval = TimeSpan.FromMilliseconds(300)
        };
        _animTimer.Tick += OnAnimTick;

        UpdateDisplay("idle", null);
        DrawBuiltinPet("idle");

        // Start HTTP event receiver on background thread
        _receiver = new EventReceiver(port);
        _receiver.StatusProvider = () => new Dictionary<string, object>
        {
            ["pet_state"] = _engine.CurrentState ?? "unknown",
            ["pet_mode"] = _petMode ? "PET" : "DEBUG",
            ["has_sprites"] = _engine.AssetManager.HasSprites,
            ["frame_count"] = _currentFrames.Length,
            ["event_count"] = _eventCount,
            ["anim_running"] = _animTimer?.IsEnabled ?? false,
        };
        _receiver.OnEvent += OnPetEvent;
        _receiverThread = new Thread(() => _receiver.Start())
        {
            IsBackground = true,
            Name = "EventReceiver"
        };
        _receiverThread.Start();

        // Bridge supervisor (optional: auto-start WSL bridge)
        _manageBridge = manageBridge;
        _connectionTimer = new DispatcherTimer
        {
            Interval = TimeSpan.FromSeconds(2)
        };
        _connectionTimer.Tick += OnConnectionTimerTick;

        if (_manageBridge)
        {
            _bridgeSupervisor = new BridgeSupervisor(port);
            _bridgeSupervisor.OnStatusChanged += OnBridgeStatusChanged;
            _bridgeSupervisor.Start();
            UpdateConnectionStatus("Starting bridge...", "#FFA500", "#FFA500"); // orange
        }

        _connectionTimer.Start();

        Closing += OnClosing;
    }

    private void OnClosing(object? sender, CancelEventArgs e)
    {
        _connectionTimer.Stop();
        _animTimer?.Stop();
        _bridgeSupervisor?.Dispose();
        _receiver.Stop();
    }

    // ── Connection status ─────────────────────────

    private void OnBridgeStatusChanged(object? sender, ConnectionStatusEventArgs e)
    {
        Dispatcher.Invoke(() =>
        {
            switch (e.Status)
            {
                case ConnectionStatus.Starting:
                    UpdateConnectionStatus("Starting bridge...", "#FFA500", "#FFA500");
                    break;
                case ConnectionStatus.Connected:
                    UpdateConnectionStatus("Connected", "#00FF88", "#00FF88");
                    break;
                case ConnectionStatus.NotConnected:
                    UpdateConnectionStatus("Not connected", "#FF6600", "#FF6600");
                    break;
                case ConnectionStatus.BridgeExited:
                    UpdateConnectionStatus($"Bridge exited: {e.Message}", "#FF4444", "#FF4444");
                    break;
                case ConnectionStatus.WslUnavailable:
                    UpdateConnectionStatus($"WSL unavailable: {e.Message}", "#FF4444", "#FF4444");
                    break;
                case ConnectionStatus.DbMissing:
                    UpdateConnectionStatus("state.db missing", "#FF4444", "#FF4444");
                    break;
            }
        });
    }

    private void OnConnectionTimerTick(object? sender, EventArgs e)
    {
        // Check if we've received an event recently (within 10 seconds)
        if (_receiver.LastEventTicks > 0)
        {
            var elapsed = DateTime.UtcNow - _receiver.LastEventTime;
            if (elapsed.TotalSeconds > 10)
            {
                // No event for 10 seconds
                _bridgeSupervisor?.NotifyTimeout();

                if (_manageBridge && _bridgeSupervisor != null)
                {
                    if (_bridgeSupervisor.Status == ConnectionStatus.Connected)
                    {
                        UpdateConnectionStatus("Not connected (timeout)", "#FF6600", "#FF6600");
                    }
                    else if (_bridgeSupervisor.Status == ConnectionStatus.BridgeExited)
                    {
                        UpdateConnectionStatus("Bridge exited", "#FF4444", "#FF4444");
                    }
                }
                else if (!_manageBridge)
                {
                    // Manual mode — just show idle status
                    if (elapsed.TotalSeconds > 30)
                        UpdateConnectionStatus("No signal (30s+)", "#FF6600", "#FF6600");
                }
            }
        }
        else
        {
            // No events ever received
            if (_manageBridge && _bridgeSupervisor != null)
            {
                switch (_bridgeSupervisor.Status)
                {
                    case ConnectionStatus.Starting:
                        // Keep showing "Starting..."
                        break;
                    case ConnectionStatus.BridgeExited:
                        UpdateConnectionStatus("Bridge exited", "#FF4444", "#FF4444");
                        break;
                    case ConnectionStatus.WslUnavailable:
                        UpdateConnectionStatus("WSL unavailable", "#FF4444", "#FF4444");
                        break;
                    default:
                        if (_receiver.LastEventTicks == 0)
                            UpdateConnectionStatus("Waiting for events...", "#888888", "#888888");
                        break;
                }
            }
            else if (!_manageBridge)
            {
                UpdateConnectionStatus("Manual mode — no events yet", "#888888", "#888888");
            }
        }
    }

    private void UpdateConnectionStatus(string text, string debugColor, string petColor)
    {
        // DEBUG mode
        ConnectionLabel.Text = text;

        // PET mode — connection dot color
        try
        {
            var color = (Color)ColorConverter.ConvertFromString(petColor);
            PetConnectionDot.Fill = new SolidColorBrush(color);
        }
        catch { }

        // Tooltip for full status
        PetConnectionDot.ToolTip = text;
    }

    private void OnPetEvent(object? sender, PetEventEventArgs e)
    {
        _bridgeSupervisor?.NotifyEventReceived();
        Dispatcher.Invoke(() =>
        {
            _eventCount++;
            UpdateDisplay(e.State, e.Payload);
        });
    }

    private void UpdateDisplay(string? state, Dictionary<string, object>? payload)
    {
        var display = _engine.MapState(state ?? "unknown", payload);

        // Extract session count from payload (sent by multi-session bridge)
        int activeSessions = 0;
        string? dominantSid = null;
        string? liveStateSource = null;
        string? currentToolName = null;
        if (payload != null)
        {
            if (payload.TryGetValue("active_session_count", out var asc))
                int.TryParse(asc?.ToString() ?? "0", out activeSessions);
            if (payload.TryGetValue("dominant_session_id", out var dsid))
                dominantSid = dsid?.ToString();
            if (payload.TryGetValue("_live_state_source", out var lss))
                liveStateSource = lss?.ToString();
            if (payload.TryGetValue("tool_name", out var tn))
                currentToolName = tn?.ToString();
        }

        // DEBUG mode updates
        StateLabel.Text = display.DebugLabel;
        StateBorder.Background = new SolidColorBrush(display.EmotionColor);
        SpeechLabel.Text = string.IsNullOrEmpty(display.SpeechText) ? "(no message)" : display.SpeechText;
        EventCountLabel.Text = $"Events: {_eventCount}";

        // Build secondary info line (connection status + live-state details)
        var infoParts = new List<string>();
        if (liveStateSource != null)
            infoParts.Add(liveStateSource);
        if (currentToolName != null)
            infoParts.Add($"tool: {currentToolName}");
        if (infoParts.Count > 0)
            ConnectionLabel.Text = string.Join(" · ", infoParts);
        else
            ConnectionLabel.Text = "";

        if (activeSessions > 0)
            ModeLabel.Text = $"Sessions: {activeSessions}";
        else
            ModeLabel.Text = _petMode ? "PET" : "DEBUG";

        // PET mode updates
        PetSpeechLabel.Text = display.SpeechText;
        if (_debugLabelVisible)
        {
            if (activeSessions > 1)
                PetDebugOverlay.Text = $"{display.HermesState} ({activeSessions})";
            else
                PetDebugOverlay.Text = display.HermesState;
        }
        else
        {
            PetDebugOverlay.Text = "";
        }

        // Animation frames
        _currentFrames = display.Frames;
        _currentFrameIndex = 0;

        if (_petMode && _currentFrames.Length > 0)
        {
            DrawAnimationFrame(0);
            StartAnimation();
        }

        // Mode label (only if not already showing session count)
        if (activeSessions <= 0)
            ModeLabel.Text = _petMode ? "PET" : "DEBUG";
    }

    private void UpdateModeVisibility()
    {
        DebugPanel.Visibility = _petMode ? Visibility.Collapsed : Visibility.Visible;
        PetPanel.Visibility = _petMode ? Visibility.Visible : Visibility.Collapsed;

        // Adjust window size based on mode
        if (_petMode)
        {
            Height = 240;
            Width = 240;
        }
        else
        {
            Height = 220;
            Width = 280;
        }

        if (_petMode && _currentFrames.Length > 0)
        {
            DrawAnimationFrame(_currentFrameIndex);
            StartAnimation();
        }
        else
        {
            _animTimer?.Stop();
        }
    }

    // ── Animation ──────────────────────────────────

    private void StartAnimation()
    {
        if (_currentFrames.Length <= 1)
        {
            _animTimer?.Stop();
            return;
        }
        if (_animTimer != null && !_animTimer.IsEnabled)
        {
            _animTimer.Interval = TimeSpan.FromMilliseconds(_currentFrames[0].DurationMs);
            _animTimer.Start();
        }
    }

    private void OnAnimTick(object? sender, EventArgs e)
    {
        if (_currentFrames.Length == 0) return;

        int nextIndex = _currentFrameIndex + 1;

        // If non-looping and this advances past the last frame, stop
        if (nextIndex >= _currentFrames.Length)
        {
            if (_currentFrames.Length > 0 && !_currentFrames[0].Loop)
            {
                _animTimer?.Stop();
                return;
            }
            nextIndex = 0; // wrap for looping animations
        }

        _currentFrameIndex = nextIndex;
        DrawAnimationFrame(_currentFrameIndex);

        if (_currentFrameIndex < _currentFrames.Length)
        {
            _animTimer!.Interval = TimeSpan.FromMilliseconds(
                _currentFrames[_currentFrameIndex].DurationMs > 0
                    ? _currentFrames[_currentFrameIndex].DurationMs
                    : 300);
        }
    }

    private void DrawAnimationFrame(int index)
    {
        if (index < 0 || index >= _currentFrames.Length) return;
        var frame = _currentFrames[index];

        if (frame.Source != null)
        {
            // Spritesheet loaded — show image, hide canvas
            PetSpriteImage.Source = frame.Source;
            PetSpriteImage.Visibility = Visibility.Visible;
            PetCanvas.Visibility = Visibility.Collapsed;
        }
        else
        {
            // No sprite — show built-in shape renderer
            PetSpriteImage.Visibility = Visibility.Collapsed;
            PetCanvas.Visibility = Visibility.Visible;
            DrawBuiltinPet(_engine.CurrentState ?? "idle");
        }
    }

    // ── Built-in Pet Renderer ──────────────────────

    private void DrawBuiltinPet(string state)
    {
        if (!_petMode) return;

        PetCanvas.Children.Clear();

        int idx = Array.IndexOf(StateNames, state);
        if (idx < 0) idx = 7;

        // Get colors from the current pet's theme (via engine)
        var display = _engine.MapState(state, null);
        Color bodyColor = display.PetBodyColor;
        Color accentColor = display.PetAccentColor;
        Color eyeColor = display.PetEyeColor;

        double cx = PetCanvas.Width / 2;
        double cy = PetCanvas.Height / 2;
        double bodyR = 20;

        // Body (circle) — use pet's body color
        var body = new Ellipse
        {
            Width = bodyR * 2,
            Height = bodyR * 2,
            Fill = new SolidColorBrush(bodyColor),
            Stroke = new SolidColorBrush(accentColor),
            StrokeThickness = 1.5,
            Opacity = 0.9,
        };
        Canvas.SetLeft(body, cx - bodyR);
        Canvas.SetTop(body, cy - bodyR);
        PetCanvas.Children.Add(body);

        // Eyes
        double eyeY = cy - 4;
        double eyeOffsetX = 5;
        double eyeR = 3;

        // Eye whites — use accent color
        var leftEye = new Ellipse { Width = eyeR * 2, Height = eyeR * 2, Fill = new SolidColorBrush(accentColor) };
        Canvas.SetLeft(leftEye, cx - eyeOffsetX - eyeR);
        Canvas.SetTop(leftEye, eyeY - eyeR);
        PetCanvas.Children.Add(leftEye);

        var rightEye = new Ellipse { Width = eyeR * 2, Height = eyeR * 2, Fill = Brushes.White };
        Canvas.SetLeft(rightEye, cx + eyeOffsetX - eyeR);
        Canvas.SetTop(rightEye, eyeY - eyeR);
        PetCanvas.Children.Add(rightEye);

        // Pupils (different positions per state)
        double pupilR = 1.8;
        double pupilOffX = 0;
        double pupilOffY = 0;

        switch (state)
        {
            case "listening":
                pupilOffX = 1.5; break;  // Look right
            case "thinking":
                pupilOffY = -1.5; break; // Look up
            case "tool_running":
                pupilOffX = -1.5; break; // Look left
            case "waiting_for_jack":
                pupilOffX = 1; pupilOffY = 1; break; // Tilt
            case "error":
                pupilOffX = 0; pupilOffY = 0; break;
            default:
                break; // Center
        }

        Color pupilColor = eyeColor;  // Use pet's eye color
        var leftPupil = new Ellipse { Width = pupilR * 2, Height = pupilR * 2, Fill = new SolidColorBrush(pupilColor) };
        Canvas.SetLeft(leftPupil, cx - eyeOffsetX - pupilR + pupilOffX);
        Canvas.SetTop(leftPupil, eyeY - pupilR + pupilOffY);
        PetCanvas.Children.Add(leftPupil);

        var rightPupil = new Ellipse { Width = pupilR * 2, Height = pupilR * 2, Fill = new SolidColorBrush(pupilColor) };
        Canvas.SetLeft(rightPupil, cx + eyeOffsetX - pupilR + pupilOffX);
        Canvas.SetTop(rightPupil, eyeY - pupilR + pupilOffY);
        PetCanvas.Children.Add(rightPupil);

        // Mouth
        double mouthY = cy + 6;
        switch (state)
        {
            case "idle":
            case "unknown":
                // Small smile
                PetCanvas.Children.Add(new Line
                {
                    X1 = cx - 4, Y1 = mouthY,
                    X2 = cx + 4, Y2 = mouthY,
                    Stroke = Brushes.White,
                    StrokeThickness = 1.5,
                });
                break;
            case "listening":
                // Open mouth
                PetCanvas.Children.Add(new Ellipse
                {
                    Width = 6, Height = 5,
                    Fill = Brushes.White,
                }); var mouth = PetCanvas.Children[^1] as Ellipse;
                if (mouth != null) { Canvas.SetLeft(mouth, cx - 3); Canvas.SetTop(mouth, mouthY - 2); }
                break;
            case "thinking":
                // Curved mouth (upward arc with line)
                PetCanvas.Children.Add(new Path
                {
                    Data = StreamGeometry.Parse($"M {cx - 4},{mouthY + 1} Q {cx},{mouthY - 3} {cx + 4},{mouthY + 1}"),
                    Stroke = Brushes.White,
                    StrokeThickness = 1.5,
                });
                break;
            case "tool_running":
                // Determined straight line
                PetCanvas.Children.Add(new Line
                {
                    X1 = cx - 5, Y1 = mouthY,
                    X2 = cx + 5, Y2 = mouthY,
                    Stroke = Brushes.White,
                    StrokeThickness = 2,
                });
                break;
            case "waiting_for_jack":
                // Question mark shape
                PetCanvas.Children.Add(new Path
                {
                    Data = StreamGeometry.Parse($"M {cx - 4},{mouthY - 2} Q {cx},{mouthY - 5} {cx + 4},{mouthY - 2} Q {cx + 6},{mouthY + 1} {cx},{mouthY + 2}"),
                    Stroke = Brushes.White,
                    StrokeThickness = 1.5,
                });
                break;
            case "done":
                // Big smile
                PetCanvas.Children.Add(new Path
                {
                    Data = StreamGeometry.Parse($"M {cx - 5},{mouthY} Q {cx},{mouthY + 5} {cx + 5},{mouthY}"),
                    Stroke = Brushes.White,
                    StrokeThickness = 2,
                });
                break;
            case "error":
                // Frown
                PetCanvas.Children.Add(new Path
                {
                    Data = StreamGeometry.Parse($"M {cx - 5},{mouthY + 2} Q {cx},{mouthY - 2} {cx + 5},{mouthY + 2}"),
                    Stroke = Brushes.Red,
                    StrokeThickness = 2,
                });
                break;
        }
    }

    // ── Right-Click Menu ───────────────────────────

    protected override void OnMouseLeftButtonDown(MouseButtonEventArgs e)
    {
        // Left-click drag for the entire window (WindowStyle=None, no title bar)
        base.OnMouseLeftButtonDown(e);
        try
        {
            DragMove();
        }
        catch (InvalidOperationException)
        {
            // DragMove can throw if the mouse button isn't actually held.
            // This is harmless — just ignore it.
        }
    }

    protected override void OnMouseRightButtonDown(MouseButtonEventArgs e)
    {
        ShowContextMenu();
        e.Handled = true;
    }

    private void ShowContextMenu()
    {
        var menu = new ContextMenu();

        // Header
        var stateItem = new MenuItem
        {
            Header = $"State: {_engine.CurrentState ?? "idle"} — {(_petMode ? "PET" : "DEBUG")}",
            IsEnabled = false,
            FontWeight = FontWeights.Bold,
        };
        menu.Items.Add(stateItem);
        menu.Items.Add(new Separator());

        // Mode switch
        var modeItem = new MenuItem
        {
            Header = _petMode ? "Switch to DEBUG Mode" : "Switch to PET Mode",
        };
        modeItem.Click += (_, _) => ToggleMode();
        menu.Items.Add(modeItem);

        // Toggle debug label
        var labelItem = new MenuItem
        {
            Header = _debugLabelVisible ? "Hide Debug Label" : "Show Debug Label",
        };
        labelItem.Click += (_, _) =>
        {
            _debugLabelVisible = !_debugLabelVisible;
            PetDebugOverlay.Visibility = _debugLabelVisible ? Visibility.Visible : Visibility.Collapsed;
        };
        menu.Items.Add(labelItem);

        // Reload pet assets
        var reloadItem = new MenuItem { Header = "Reload Pet Assets" };
        reloadItem.Click += (_, _) =>
        {
            _engine.LoadPet(_engine.AssetManager.CurrentPet);
            UpdateDisplay(_engine.CurrentState ?? "idle", null);
        };
        menu.Items.Add(reloadItem);

        // Select Pet submenu
        var petMenu = new MenuItem { Header = "Select Pet" };
        var availablePets = _engine.AssetManager.ListAvailablePets();
        foreach (var petName in availablePets)
        {
            var petItem = new MenuItem
            {
                Header = petName,
                IsChecked = petName == _engine.AssetManager.CurrentPet,
            };
            var capturedName = petName; // capture for closure
            petItem.Click += (_, _) =>
            {
                if (_engine.LoadPet(capturedName))
                {
                    UpdateDisplay(_engine.CurrentState ?? "idle", null);
                    DrawBuiltinPet(_engine.CurrentState ?? "idle");
                }
            };
            petMenu.Items.Add(petItem);
        }
        menu.Items.Add(petMenu);

        menu.Items.Add(new Separator());

        // Manual state switch
        var stateMenu = new MenuItem { Header = "Switch State" };
        foreach (var s in new[] { "idle", "listening", "thinking", "tool_running",
                                   "waiting_for_jack", "done", "error" })
        {
            var item = new MenuItem { Header = s };
            item.Click += (_, _) => UpdateDisplay(s, null);
            stateMenu.Items.Add(item);
        }
        menu.Items.Add(stateMenu);
        menu.Items.Add(new Separator());

        // Position controls
        var centerItem = new MenuItem { Header = "Center on Screen" };
        centerItem.Click += (_, _) =>
        {
            Left = (SystemParameters.PrimaryScreenWidth - Width) / 2;
            Top = (SystemParameters.PrimaryScreenHeight - Height) / 2;
        };
        menu.Items.Add(centerItem);

        var resetPosItem = new MenuItem { Header = "Reset Position" };
        resetPosItem.Click += (_, _) =>
        {
            Left = SystemParameters.WorkArea.Right - Width - 20;
            Top = SystemParameters.WorkArea.Bottom - Height - 20;
        };
        menu.Items.Add(resetPosItem);

        menu.Items.Add(new Separator());

        var resetItem = new MenuItem { Header = "Reset to Idle" };
        resetItem.Click += (_, _) => UpdateDisplay("idle", null);
        menu.Items.Add(resetItem);

        var quitItem = new MenuItem { Header = "Exit" };
        quitItem.Click += (_, _) => Close();
        menu.Items.Add(quitItem);

        menu.PlacementTarget = this;
        menu.IsOpen = true;
    }

    private void ToggleMode()
    {
        _petMode = !_petMode;
        _engine.PetMode = _petMode;
        UpdateModeVisibility();
        UpdateDisplay(_engine.CurrentState ?? "idle", null);
    }
}
