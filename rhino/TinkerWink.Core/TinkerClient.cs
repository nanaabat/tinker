using System;
using System.IO;
using System.Net.Http;
using System.Net.Http.Headers;
using System.Text;
using System.Text.Json;
using System.Threading;
using System.Threading.Tasks;

namespace TinkerWink.Core
{
    /// <summary>Loopback-only client for tinker-service. Refuses non-loopback addresses.</summary>
    public sealed class TinkerClient
    {
        readonly HttpClient _http;
        readonly Func<string> _token;
        public Uri BaseUri { get; }

        public TinkerClient(int port, string tokenFile, HttpMessageHandler? handler = null)
            : this(new Uri($"http://127.0.0.1:{port}"), () => File.ReadAllText(tokenFile).Trim(), handler) { }

        public TinkerClient(Uri baseUri, Func<string> token, HttpMessageHandler? handler = null)
        {
            if (!(baseUri.Host == "127.0.0.1" || baseUri.Host == "localhost")) throw new ArgumentException("tinker-service must be on loopback");
            BaseUri = baseUri;
            _token = token;
            _http = handler == null ? new HttpClient() : new HttpClient(handler);
            _http.Timeout = TimeSpan.FromMinutes(5);
        }

        public async Task<JsonDocument> SendAsync(HttpMethod method, string path, object? body, CancellationToken ct = default)
        {
            using var req = new HttpRequestMessage(method, new Uri(BaseUri, path));
            req.Headers.Authorization = new AuthenticationHeaderValue("Bearer", _token());
            if (body != null) req.Content = new StringContent(JsonSerializer.Serialize(body), Encoding.UTF8, "application/json");
            using var res = await _http.SendAsync(req, ct).ConfigureAwait(false);
            var text = await res.Content.ReadAsStringAsync().ConfigureAwait(false);
            if (!res.IsSuccessStatusCode) throw new InvalidOperationException($"tinker service {(int)res.StatusCode}: {text}");
            return JsonDocument.Parse(text);
        }

        public Task<JsonDocument> HealthAsync(CancellationToken ct = default) => SendAsync(HttpMethod.Get, "/v1/health", null, ct);
        public Task<JsonDocument> LearnAsync(object scene, object demos, string name, CancellationToken ct = default) =>
            SendAsync(HttpMethod.Post, "/v1/learn", new { scene, demonstrations = demos, name }, ct);
        public Task<JsonDocument> PlanAsync(object scene, string skill, string objectId, string joint, double goal, CancellationToken ct = default) =>
            SendAsync(HttpMethod.Post, "/v1/plan", new { scene, skill, object_id = objectId, joint, goal_value = goal }, ct);
    }
}
