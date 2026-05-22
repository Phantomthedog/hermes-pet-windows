using System;
using System.Threading;
using System.Windows;

namespace HermesPet;

/// <summary>
/// Hermes Pet — Windows floating overlay for Hermes Agent state visualization.
/// Now acts as a supervisor: starts the WSL bridge automatically by default.
///
/// Usage:
///   HermesPet.exe                          # overlay + managed bridge
///   HermesPet.exe --no-bridge              # overlay only (manual bridge)
///   HermesPet.exe --port 5731 --x 100 --y 100
/// </summary>
public class Program
{
    private static Mutex? _mutex;

    [STAThread]
    public static void Main(string[] args)
    {
        // Parse command-line arguments
        int port = 5731;
        double? initialX = null;
        double? initialY = null;
        bool manageBridge = true;

        for (int i = 0; i < args.Length; i++)
        {
            switch (args[i])
            {
                case "--port" when i + 1 < args.Length:
                    port = int.Parse(args[++i]);
                    break;
                case "--x" when i + 1 < args.Length:
                    initialX = double.Parse(args[++i]);
                    break;
                case "--y" when i + 1 < args.Length:
                    initialY = double.Parse(args[++i]);
                    break;
                case "--no-bridge":
                case "--manage-bridge":
                    // --no-bridge: manageBridge = false
                    // --manage-bridge false: manageBridge = false
                    if (i + 1 < args.Length && args[i + 1] == "false")
                    {
                        manageBridge = false;
                        i++;
                    }
                    else if (args[i] == "--no-bridge")
                    {
                        manageBridge = false;
                    }
                    break;
                case "--help":
                    Console.WriteLine("Usage: HermesPet [--port PORT] [--x X] [--y Y] [--no-bridge]");
                    return;
            }
        }

        // Single instance check
        bool createdNew;
        _mutex = new Mutex(true, "HermesPet-Overlay", out createdNew);
        if (!createdNew)
        {
            Console.Error.WriteLine("Hermes Pet is already running (another instance found)");
            Environment.Exit(1);
        }

        var app = new Application();

        var window = new MainWindow(port, initialX, initialY, manageBridge);
        app.Run(window);
    }
}
