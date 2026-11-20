using System;
using System.Collections.Generic;
using TinkerWink.Contracts;

namespace TinkerWink.Core
{
    /// <summary>Host-independent recorder: rate-limits pose samples, always keeps edit/undo/redo events,
    /// ignores other objects, keeps time monotonic. Mirrors tinker_learning.Recorder.</summary>
    public sealed class DemoRecorder
    {
        public string ObjectId { get; }
        public double MinInterval { get; }
        public bool Recording { get; private set; }
        readonly List<Sample> _samples = new List<Sample>();
        double? _t0;
        double _lastT = double.NegativeInfinity;

        public DemoRecorder(string objectId, double minInterval = 1.0 / 60) { ObjectId = objectId; MinInterval = minInterval; }
        public IReadOnlyList<Sample> Samples => _samples;

        public void Start() { if (Recording) throw new InvalidOperationException("already recording"); Recording = true; _samples.Clear(); _t0 = null; _lastT = double.NegativeInfinity; }

        public void OnChange(string objectId, Pose pose, double t, string ev = "sample")
        {
            if (!Recording || objectId != ObjectId) return;
            _t0 ??= t;
            var rel = t - _t0.Value;
            if (rel < 0) return;
            if (ev == "sample" && rel - _lastT < MinInterval) return;
            if (_samples.Count > 0 && rel < _samples[_samples.Count - 1].T) rel = _samples[_samples.Count - 1].T;
            _lastT = rel;
            _samples.Add(new Sample { T = Math.Round(rel, 6), Poses = new Dictionary<string, Pose> { [objectId] = pose }, Action = null, Event = ev });
        }

        public Demonstration Stop(string sceneId, string jointName, double finalValue, string? id = null)
        {
            if (!Recording) throw new InvalidOperationException("not recording");
            Recording = false;
            if (_samples.Count < 2) throw new InvalidOperationException("demonstration is empty: move the selected object while recording");
            return new Demonstration
            {
                SchemaVersion = SchemaInfo.Version, Id = id ?? "demo-" + Guid.NewGuid().ToString("N").Substring(0, 12), SceneId = sceneId,
                ObjectIds = new List<string> { ObjectId }, Samples = new List<Sample>(_samples),
                Goal = new DemonstrationGoal { ObjectId = ObjectId, Joint = jointName, TargetValue = finalValue },
                Context = new Dictionary<string, System.Text.Json.JsonElement>(), UserCorrections = new List<string>(),
            };
        }
    }
}
