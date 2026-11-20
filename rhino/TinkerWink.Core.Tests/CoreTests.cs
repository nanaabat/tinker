using System;
using System.IO;
using System.Linq;
using System.Net;
using System.Net.Http;
using System.Text.Json;
using System.Threading;
using System.Threading.Tasks;
using TinkerWink.Contracts;
using TinkerWink.Core;
using Xunit;

public class CoreTests
{
    static readonly JsonDocument Vectors = JsonDocument.Parse(File.ReadAllText(Path.Combine(AppContext.BaseDirectory, "vectors", "kinematics.json")));

    [Fact]
    public void FixtureSnapshotRoundTripsThroughGeneratedTypes()
    {
        var raw = Vectors.RootElement.GetProperty("scene").GetRawText();
        var snap = JsonSerializer.Deserialize<SceneSnapshot>(raw)!;
        Assert.Equal("1.0.0", snap.SchemaVersion);
        Assert.Equal(SchemaInfo.Version, snap.SchemaVersion);
        var again = JsonSerializer.Deserialize<SceneSnapshot>(JsonSerializer.Serialize(snap))!;
        Assert.Equal(snap.Objects.Count, again.Objects.Count);
        Assert.Equal(snap.Objects.Select(o => o.Id), again.Objects.Select(o => o.Id));
    }

    [Fact]
    public void KinematicsMatchesPythonReference()
    {
        var snap = JsonSerializer.Deserialize<SceneSnapshot>(Vectors.RootElement.GetProperty("scene").GetRawText())!;
        int n = 0;
        foreach (var c in Vectors.RootElement.GetProperty("cases").EnumerateArray())
        {
            var obj = snap.Objects.First(o => o.Id == c.GetProperty("object_id").GetString());
            var j = obj.Joints.First(x => x.Name == c.GetProperty("joint").GetString());
            var v = c.GetProperty("value").GetDouble();
            var pose = Kinematics.PoseForValue(obj, j, v);
            var exp = JsonSerializer.Deserialize<Pose>(c.GetProperty("pose").GetRawText())!;
            for (int i = 0; i < 3; i++) Assert.Equal(exp.Position[i], pose.Position[i], 9);
            for (int i = 0; i < 4; i++) Assert.Equal(exp.Rotation[i], pose.Rotation[i], 9);
            Assert.Equal(v, Kinematics.ValueFromPose(obj, j, pose), 9);
            n++;
        }
        Assert.True(n >= 10);
    }

    [Fact]
    public void RecorderRateLimitsAndKeepsEdits()
    {
        var r = new DemoRecorder("a", 0.02);
        r.Start();
        var p = new Pose { Position = new() { 0, 0, 0 }, Rotation = new() { 1, 0, 0, 0 } };
        for (int k = 0; k < 1000; k++) r.OnChange("a", p, k / 1000.0);
        r.OnChange("b", p, 0.5, "edit");
        r.OnChange("a", p, 1.0005, "edit");
        Assert.InRange(r.Samples.Count, 45, 55);
        Assert.Equal("edit", r.Samples.Last().Event);
        var d = r.Stop("scene", "slide", 1.0);
        Assert.Equal("1.0.0", d.SchemaVersion);
        Assert.Throws<InvalidOperationException>(() => r.Stop("scene", "slide", 1.0));
    }

    [Fact]
    public void EmptyDemonstrationRejected()
    {
        var r = new DemoRecorder("a");
        r.Start();
        Assert.Throws<InvalidOperationException>(() => r.Stop("s", "j", 0));
    }

    sealed class Capture : HttpMessageHandler
    {
        public HttpRequestMessage? Last;
        protected override Task<HttpResponseMessage> SendAsync(HttpRequestMessage request, CancellationToken ct)
        {
            Last = request;
            return Task.FromResult(new HttpResponseMessage(HttpStatusCode.OK) { Content = new StringContent("{\"ok\":true}") });
        }
    }

    [Fact]
    public async Task ClientSendsBearerTokenToLoopbackOnly()
    {
        var h = new Capture();
        var c = new TinkerClient(new Uri("http://127.0.0.1:47615"), () => "tok123", h);
        var res = await c.HealthAsync();
        Assert.True(res.RootElement.GetProperty("ok").GetBoolean());
        Assert.Equal("Bearer", h.Last!.Headers.Authorization!.Scheme);
        Assert.Equal("tok123", h.Last.Headers.Authorization.Parameter);
        Assert.Throws<ArgumentException>(() => new TinkerClient(new Uri("http://example.com:47615"), () => "x"));
    }
}
