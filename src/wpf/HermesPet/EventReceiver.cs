using System;
using System.Collections.Generic;
using System.IO;
using System.Net;
using System.Net.Sockets;
using System.Text;
using System.Text.Json;
using System.Threading;

namespace HermesPet;

/// <summary>
/// Event arguments carrying a parsed pet event.
/// </summary>
public class PetEventEventArgs : EventArgs
{
    public string? EventType { get; set; }
    public string? State { get; set; }
    public string? Timestamp { get; set; }
    public Dictionary<string, object>? Payload { get; set; }
}

/// <summary>
/// TCP-based HTTP server that receives events from the WSL bridge watcher.
/// Listens on http://127.0.0.1:{Port}/event/ for POST requests.
/// Uses TcpListener instead of HttpListener to avoid http.sys URL ACL requirements.
/// </summary>
public class EventReceiver
{
    private readonly int _port;
    private TcpListener? _listener;
    private volatile bool _running;
    private Thread? _acceptThread;
    private long _lastEventTicks;

    /// <summary>UTC ticks of the last received event. 0 if none.</summary>
    public long LastEventTicks => _lastEventTicks;

    /// <summary>UTC DateTime of the last received event. DateTime.MinValue if none.</summary>
    public DateTime LastEventTime => _lastEventTicks > 0
        ? new DateTime(_lastEventTicks, DateTimeKind.Utc)
        : DateTime.MinValue;

    /// <summary>
    /// Fired when a valid pet event is received. Raised from the listener thread.
    /// </summary>
    public event EventHandler<PetEventEventArgs>? OnEvent;

    public EventReceiver(int port)
    {
        _port = port;
    }

    /// <summary>
    /// Start the TCP listener (blocking). Call from background thread.
    /// </summary>
    public void Start()
    {
        try
        {
            _listener = new TcpListener(IPAddress.Any, _port);
            _listener.Start();
            _running = true;
            _acceptThread = new Thread(AcceptLoop)
            {
                IsBackground = true,
                Name = "EventReceiver"
            };
            _acceptThread.Start();
        }
        catch (Exception ex)
        {
            System.Diagnostics.Debug.WriteLine($"EventReceiver start error: {ex.Message}");
        }
    }

    private void AcceptLoop()
    {
        while (_running)
        {
            try
            {
                var client = _listener!.AcceptTcpClient();
                ThreadPool.QueueUserWorkItem(ProcessClient, client);
            }
            catch (ObjectDisposedException)
            {
                break;
            }
            catch (InvalidOperationException)
            {
                break;
            }
            catch (Exception ex)
            {
                System.Diagnostics.Debug.WriteLine($"EventReceiver accept error: {ex.Message}");
            }
        }
    }

    private void ProcessClient(object? state)
    {
        if (state is not TcpClient client)
            return;

        try
        {
            using (client)
            using (var stream = client.GetStream())
            {
                // Read the HTTP request
                var buffer = new byte[65536];
                int totalRead = 0;
                int bytesRead;

                do
                {
                    bytesRead = stream.Read(buffer, totalRead, Math.Min(4096, buffer.Length - totalRead));
                    if (bytesRead == 0) break;
                    totalRead += bytesRead;

                    // Check if we've read the full request (headers terminated by \r\n\r\n)
                    string headerCheck = Encoding.ASCII.GetString(buffer, 0, totalRead);
                    if (headerCheck.Contains("\r\n\r\n"))
                    {
                        // Check for Content-Length to know when body is complete
                        int contentLength = 0;
                        foreach (var line in headerCheck.Split('\r'))
                        {
                            if (line.StartsWith("Content-Length:", StringComparison.OrdinalIgnoreCase))
                            {
                                int.TryParse(line.AsSpan("Content-Length:".Length), out contentLength);
                            }
                        }

                        if (contentLength > 0)
                        {
                            int headerEnd = headerCheck.IndexOf("\r\n\r\n") + 4;
                            int bodySize = totalRead - headerEnd;
                            if (bodySize >= contentLength)
                                break; // Full body received
                        }
                        else
                        {
                            break; // No content-length, assume request complete after headers
                        }
                    }
                } while (totalRead < buffer.Length);

                string request = Encoding.UTF8.GetString(buffer, 0, totalRead);

                // Parse the request line to check method and path
                var requestLines = request.Split('\n');
                string requestLine = requestLines.Length > 0 ? requestLines[0].Trim() : "";

                // Extract body (after \r\n\r\n)
                int bodyStart = request.IndexOf("\r\n\r\n");
                string body = bodyStart >= 0
                    ? request.Substring(bodyStart + 4).Trim()
                    : "";

                // Only accept POST to /event/
                if (!requestLine.StartsWith("POST /event/") &&
                    !requestLine.StartsWith("POST /event ") &&
                    !requestLine.StartsWith("POST /event"))
                {
                    SendTcpResponse(stream, 404, new { status = "error", message = "Not found" });
                    return;
                }

                if (string.IsNullOrEmpty(body))
                {
                    SendTcpResponse(stream, 400, new { status = "error", message = "Empty body" });
                    return;
                }

                // Parse JSON
                using var doc = JsonDocument.Parse(body);
                var root = doc.RootElement;

                // Validate required fields
                if (!root.TryGetProperty("event_type", out var eventTypeEl) ||
                    !root.TryGetProperty("state", out var stateEl))
                {
                    SendTcpResponse(stream, 400,
                        new { status = "error", message = "Missing event_type or state" });
                    return;
                }

                string? eventType = eventTypeEl.GetString();
                string? petState = stateEl.GetString();
                string? timestamp = root.TryGetProperty("timestamp", out var tsEl)
                    ? tsEl.GetString() : null;

                // Extract payload
                var payload = new Dictionary<string, object>();
                if (root.TryGetProperty("payload", out var payloadEl) &&
                    payloadEl.ValueKind == JsonValueKind.Object)
                {
                    foreach (var prop in payloadEl.EnumerateObject())
                    {
                        var val = NormalizeJsonValue(prop.Value);
                        if (val != null)
                            payload[prop.Name] = val;
                    }
                }

                // Fire event
                var args = new PetEventEventArgs
                {
                    EventType = eventType,
                    State = petState,
                    Timestamp = timestamp,
                    Payload = payload,
                };
                OnEvent?.Invoke(this, args);
                _lastEventTicks = DateTime.UtcNow.Ticks;

                SendTcpResponse(stream, 200, new { status = "ok" });
            }
        }
        catch (JsonException ex)
        {
            TrySendError(client, 400, $"Invalid JSON: {ex.Message}");
        }
        catch (Exception)
        {
            // Client disconnected or other transient error — silently ignore
        }
    }

    private static void SendTcpResponse(NetworkStream stream, int statusCode, object data)
    {
        string json = JsonSerializer.Serialize(data, new JsonSerializerOptions
        {
            PropertyNamingPolicy = JsonNamingPolicy.SnakeCaseLower
        });
        byte[] body = Encoding.UTF8.GetBytes(json);
        string statusText = statusCode == 200 ? "OK" : statusCode == 400 ? "Bad Request" : "Not Found";

        string header = $"HTTP/1.1 {statusCode} {statusText}\r\n" +
                        "Content-Type: application/json\r\n" +
                        $"Content-Length: {body.Length}\r\n" +
                        "Connection: close\r\n" +
                        "\r\n";

        byte[] headerBytes = Encoding.ASCII.GetBytes(header);
        stream.Write(headerBytes, 0, headerBytes.Length);
        stream.Write(body, 0, body.Length);
    }

    private static void TrySendError(TcpClient client, int statusCode, string message)
    {
        try
        {
            using var stream = client.GetStream();
            SendTcpResponse(stream, statusCode, new { status = "error", message });
        }
        catch { }
    }

    /// <summary>
    /// Convert a JsonElement to its native CLR type, avoiding GetRawText() quoting issues.
    /// </summary>
    private static object? NormalizeJsonValue(JsonElement element)
    {
        return element.ValueKind switch
        {
            JsonValueKind.String => element.GetString(),
            JsonValueKind.Number => element.TryGetInt32(out var i) ? i : element.GetDouble(),
            JsonValueKind.True => true,
            JsonValueKind.False => false,
            JsonValueKind.Null => null,
            _ => element.GetRawText(), // object/array — keep as JSON text
        };
    }

    /// <summary>
    /// Stop the TCP listener.
    /// </summary>
    public void Stop()
    {
        _running = false;
        try
        {
            _listener?.Stop();
        }
        catch (ObjectDisposedException) { }
    }

    /// <summary>
    /// Simple health check method (for testing).
    /// </summary>
    public string GetStatus() => _running ? "running" : "stopped";
}
