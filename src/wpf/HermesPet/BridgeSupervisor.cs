using System;
using System.ComponentModel;
using System.Diagnostics;
using System.IO;
using System.Text;

namespace HermesPet;

/// <summary>
/// Bridge connection status.
/// </summary>
public enum ConnectionStatus
{
    NotConnected,
    Starting,
    Connected,
    BridgeExited,
    WslUnavailable,
    DbMissing,
}

/// <summary>
/// Status change event args.
/// </summary>
public class ConnectionStatusEventArgs : EventArgs
{
    public ConnectionStatus Status { get; set; }
    public string? Message { get; set; }
}

/// <summary>
/// Manages the WSL bridge watcher process from the Windows overlay.
/// Starts wsl.exe, monitors the process, and reports connection status.
/// </summary>
public class BridgeSupervisor : IDisposable
{
    private Process? _process;
    private readonly int _port;
    private volatile bool _disposed;
    private bool _bridgeStartedByMe;
    private readonly string _projectDirWsl;
    private readonly string _stateDbPath;
    private readonly string _logDirWindows;

    /// <summary>
    /// Create a bridge supervisor.
    /// </summary>
    /// <param name="port">Port the overlay is listening on (sent to bridge as overlay URL).</param>
    /// <param name="projectDirWsl">WSL path to the project root (e.g. /mnt/c/Users/.../hermes-pet).
    /// Auto-detected if null.</param>
    /// <param name="stateDbPath">Path to Hermes state.db in WSL.
    /// Defaults to $HOME/.hermes/profiles/phantom/state.db if null.</param>
    /// <param name="logDirWindows">Windows path for logs. Defaults to a logs/ subfolder
    /// next to the executable if null.</param>
    public BridgeSupervisor(
        int port,
        string? projectDirWsl = null,
        string? stateDbPath = null,
        string? logDirWindows = null)
    {
        _port = port;

        // Project root in WSL: auto-detect from the assembly location
        if (projectDirWsl != null)
        {
            _projectDirWsl = projectDirWsl;
        }
        else
        {
            // Walk up from assembly location to find the project root
            var asmPath = System.Reflection.Assembly.GetExecutingAssembly().Location;
            var dir = new DirectoryInfo(Path.GetDirectoryName(asmPath) ?? ".");
            // Walk up from bin/Release/net8.0-windows/win-x64/ to project root
            while (dir != null && !dir.Name.Equals("hermes-pet", StringComparison.OrdinalIgnoreCase))
                dir = dir.Parent;
            string? windowsProjectDir = dir?.FullName;
            if (windowsProjectDir != null)
            {
                // Convert Windows path to WSL path
                string drive = windowsProjectDir.Substring(0, 1).ToLower();
                string rest = windowsProjectDir.Substring(2).Replace('\\', '/');
                _projectDirWsl = $"/mnt/{drive}{rest}";
            }
            else
            {
                // Fallback: use a sensible default for common setups
                _projectDirWsl = "/mnt/c/Users/Public/hermes-pet";
            }
        }

        _stateDbPath = stateDbPath ?? "$(getent passwd $(whoami) | cut -d: -f6)/.hermes/profiles/phantom/state.db";
        _logDirWindows = logDirWindows ?? Path.Combine(
            Path.GetDirectoryName(System.Reflection.Assembly.GetExecutingAssembly().Location) ?? ".",
            "..", "..", "..", "..", "..", "logs");
    }
    public ConnectionStatus Status { get; private set; } = ConnectionStatus.NotConnected;

    /// <summary>Whether the bridge process was started by this instance.</summary>
    public bool IsManaged => _bridgeStartedByMe && _process != null;

    /// <summary>Whether the bridge is running/connected.</summary>
    public bool IsConnected => Status == ConnectionStatus.Connected;

    /// <summary>Fired when bridge connection status changes.</summary>
    public event EventHandler<ConnectionStatusEventArgs>? OnStatusChanged;

    /// <summary>
    /// Start the WSL bridge process.
    /// </summary>
    public void Start()
    {
        if (_process != null && !_process.HasExited)
        {
            UpdateStatus(ConnectionStatus.Connected, "Bridge already running");
            return;
        }

        UpdateStatus(ConnectionStatus.Starting, "Starting bridge...");

        try
        {
            // Build WSL command that dynamically detects the Windows host.
            // Note: wsl.exe bash -lc has issues with $VAR across && chains
            // (variable not available on the RHS of &&). Use inline command
            // substitution instead of an intermediate variable.
            string wslCommand =
                $"cd {_projectDirWsl} && " +
                $"python3 src/bridge_watcher.py --db-path {_stateDbPath} " +
                $"--overlay-url http://$(ip route show default | awk '{{print $3}}'):{_port}/event/ --poll-interval 1.0";

            var psi = new ProcessStartInfo
            {
                FileName = "wsl.exe",
                CreateNoWindow = true,
                UseShellExecute = false,
                RedirectStandardOutput = true,
                RedirectStandardError = true,
                StandardOutputEncoding = Encoding.UTF8,
                StandardErrorEncoding = Encoding.UTF8,
            };

            psi.ArgumentList.Add("bash");
            psi.ArgumentList.Add("-lc");
            psi.ArgumentList.Add(wslCommand);

            _process = new Process { StartInfo = psi };

            // Set up async output reading
            _process.OutputDataReceived += OnBridgeOutput;
            _process.ErrorDataReceived += OnBridgeError;

            _process.Start();
            _process.BeginOutputReadLine();
            _process.BeginErrorReadLine();

            _bridgeStartedByMe = true;

            // Monitor process exit
            _process.Exited += OnBridgeExited;
            _process.EnableRaisingEvents = true;

            UpdateStatus(ConnectionStatus.Starting, "Bridge process started");
        }
        catch (Win32Exception ex)
        {
            // wsl.exe not found
            UpdateStatus(ConnectionStatus.WslUnavailable, $"WSL unavailable: {ex.Message}");
        }
        catch (Exception ex)
        {
            UpdateStatus(ConnectionStatus.BridgeExited, $"Failed to start: {ex.Message}");
        }
    }

    /// <summary>
    /// Stop the bridge process if we started it.
    /// </summary>
    public void Stop()
    {
        if (_process != null && _bridgeStartedByMe)
        {
            try
            {
                if (!_process.HasExited)
                {
                    _process.Kill(entireProcessTree: true);
                    _process.WaitForExit(3000);
                }
            }
            catch (InvalidOperationException) { }
            catch (Win32Exception) { }

            _process.Dispose();
            _process = null;
            _bridgeStartedByMe = false;
        }

        UpdateStatus(ConnectionStatus.NotConnected, "Bridge stopped");
    }

    /// <summary>
    /// Called by EventReceiver when an event is received.
    /// Updates connection status to Connected.
    /// </summary>
    public void NotifyEventReceived()
    {
        if (Status != ConnectionStatus.Connected)
        {
            UpdateStatus(ConnectionStatus.Connected, "Events received");
        }
    }

    /// <summary>
    /// Called when the connection timeout expires (no event for N seconds).
    /// </summary>
    public void NotifyTimeout()
    {
        if (Status == ConnectionStatus.Connected)
        {
            if (_process != null && !_process.HasExited)
            {
                UpdateStatus(ConnectionStatus.NotConnected, "No heartbeat (10s timeout)");
            }
            else
            {
                UpdateStatus(ConnectionStatus.BridgeExited, "Bridge process exited");
            }
        }
    }

    private void OnBridgeOutput(object sender, DataReceivedEventArgs e)
    {
        if (!string.IsNullOrEmpty(e.Data))
        {
            AppendLog(e.Data);
        }
    }

    private void OnBridgeError(object sender, DataReceivedEventArgs e)
    {
        if (!string.IsNullOrEmpty(e.Data))
        {
            AppendLog($"STDERR: {e.Data}");
        }
    }

    private void OnBridgeExited(object? sender, EventArgs e)
    {
        if (_disposed) return;

        var exitCode = _process?.ExitCode ?? -1;
        AppendLog($"Bridge exited (code {exitCode})");

        UpdateStatus(ConnectionStatus.BridgeExited, $"Bridge exited (code {exitCode})");
    }

    private void UpdateStatus(ConnectionStatus newStatus, string? message)
    {
        Status = newStatus;
        OnStatusChanged?.Invoke(this, new ConnectionStatusEventArgs
        {
            Status = newStatus,
            Message = message,
        });
    }

    private void AppendLog(string line)
    {
        try
        {
            Directory.CreateDirectory(_logDirWindows);
            string logPath = Path.Combine(_logDirWindows, "bridge_supervisor.log");
            File.AppendAllText(logPath,
                $"{DateTime.UtcNow:yyyy-MM-dd HH:mm:ss} {line}{Environment.NewLine}");
        }
        catch
        {
            // Silently fail on log write errors
        }
    }

    public void Dispose()
    {
        _disposed = true;
        Stop();
    }
}
