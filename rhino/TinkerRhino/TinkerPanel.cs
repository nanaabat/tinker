using System;
using System.Linq;
using System.Runtime.InteropServices;
using System.Text.Json;
using System.Threading.Tasks;
using Eto.Drawing;
using Eto.Forms;
using Rhino;
using Rhino.DocObjects;
using Rhino.Geometry;
using TinkerWink.Contracts;
using TinkerWink.Core;

namespace TinkerRhino
{
    /// <summary>Dockable panel: Select -> Record -> Stop -> Learn -> Simulate -> Preview -> Apply, plus Undo.
    /// Network calls run off the UI thread; document edits are marshalled back with RhinoApp.InvokeOnUiThread.</summary>
    [Guid("a3c5e9d1-2b4f-4c6a-8e1d-7f9b0c2d4e61")]
    public sealed class TinkerPanel : Panel
    {
        readonly Label _status = new Label { Text = "select an object with a joint", Wrap = WrapMode.Word };
        readonly ProgressBar _progress = new ProgressBar { Indeterminate = false, MinValue = 0, MaxValue = 100 };
        readonly NumericStepper _goal = new NumericStepper { DecimalPlaces = 3 };
        readonly Button _select = new Button { Text = "&Select" }, _record = new Button { Text = "&Record" }, _stop = new Button { Text = "S&top" },
            _learn = new Button { Text = "&Learn" }, _simulate = new Button { Text = "Si&mulate" }, _preview = new Button { Text = "&Preview" },
            _apply = new Button { Text = "&Apply" }, _undo = new Button { Text = "&Undo" };
        Guid _target;
        DemoRecorder? _rec;
        readonly System.Collections.Generic.List<(SceneSnapshot scene, Demonstration demo)> _demos = new();
        string? _skill;
        JsonDocument? _plan;
        PreviewConduit? _conduit;
        uint _undoSerial;
        readonly DateTime _t0 = DateTime.UtcNow;

        public TinkerPanel()
        {
            _select.Click += (s, e) => Select();
            _record.Click += (s, e) => Record();
            _stop.Click += (s, e) => Stop();
            _learn.Click += async (s, e) => await Learn();
            _simulate.Click += async (s, e) => await Simulate();
            _preview.Click += (s, e) => Preview();
            _apply.Click += (s, e) => Apply();
            _undo.Click += (s, e) => { if (_undoSerial != 0) RhinoDoc.ActiveDoc.Undo(); _status.Text = "undone"; };
            Content = new StackLayout
            {
                Padding = 8, Spacing = 4, HorizontalContentAlignment = HorizontalAlignment.Stretch,
                Items = { new Label { Text = "tingle: sense, propose, apply, verify, report" }, _status, _progress, _select,
                          new StackLayout { Orientation = Orientation.Horizontal, Spacing = 4, Items = { _record, _stop } },
                          _learn, new Label { Text = "goal (scene units, or degrees for hinges)" }, _goal, _simulate, _preview, _apply, _undo,
                          new Label { Text = "sense (room, target, then read)" },
                          new Label { Text = "run the HunchRead command to predict how the space tends to feel. not a reading of a person." } },
            };
            RhinoDoc.ReplaceRhinoObject += OnReplace;
        }

        static TinkerClient Client()
        {
            var home = System.Environment.GetEnvironmentVariable("TINKER_HOME") ??
                       System.IO.Path.Combine(System.Environment.GetFolderPath(System.Environment.SpecialFolder.UserProfile), ".tinker");
            return new TinkerClient(47615, System.IO.Path.Combine(home, "token"));
        }

        double Now() => (DateTime.UtcNow - _t0).TotalSeconds;

        SceneObject? Target(out SceneSnapshot snap)
        {
            snap = RhinoConnector.Snapshot(RhinoDoc.ActiveDoc);
            var id = _target.ToString();
            return snap.Objects.FirstOrDefault(o => o.HostId == id);
        }

        void Select()
        {
            var sel = RhinoDoc.ActiveDoc.Objects.GetSelectedObjects(false, false).FirstOrDefault();
            if (sel == null || string.IsNullOrEmpty(sel.Attributes.GetUserString("tinker_joint"))) { _status.Text = "select one object that has a joint"; return; }
            _target = sel.Id;
            var so = Target(out _)!;
            var j = so.Joints[0];
            _goal.Value = j.Kind == "revolute" ? j.Value * 180 / Math.PI : j.Value;
            _status.Text = $"selected {so.Name} ({j.Kind} '{j.Name}')";
        }

        // Rhino reports a transform of an object as a Replace event; we sample its pose (command intent is not exposed).
        void OnReplace(object? sender, RhinoReplaceObjectEventArgs e)
        {
            if (_rec == null || !_rec.Recording || e.ObjectId != _target) return;
            var pose = RhinoConnector.PoseOf(e.NewRhinoObject, out _);
            _rec.OnChange(_target.ToString(), pose, Now(), "edit");
        }

        void Record()
        {
            if (_target == Guid.Empty) { _status.Text = "select first"; return; }
            _rec = new DemoRecorder(_target.ToString());
            _rec.Start();
            var o = RhinoDoc.ActiveDoc.Objects.FindId(_target);
            _rec.OnChange(_target.ToString(), RhinoConnector.PoseOf(o, out _), Now(), "sample");
            _status.Text = "recording: move the object with Rhino's tools (Gumball, Move, Rotate), then Stop";
        }

        void Stop()
        {
            if (_rec == null) return;
            var so = Target(out var snap)!;
            var j = so.Joints[0];
            var start = _rec.Samples[0].Poses[_target.ToString()];
            var startObj = new SceneObject { Id = so.Id, HostId = so.HostId, Name = so.Name, Type = so.Type, Pose = start, Size = so.Size, Collision = so.Collision, Joints = so.Joints };
            var last = _rec.Samples[_rec.Samples.Count - 1].Poses[_target.ToString()];
            var final = Kinematics.ValueFromPose(startObj, j, last);
            try
            {
                var demo = _rec.Stop(snap.SceneId, j.Name, final);
                demo.ObjectIds = new System.Collections.Generic.List<string> { so.Id };
                foreach (var smp in demo.Samples) smp.Poses = new System.Collections.Generic.Dictionary<string, Pose> { [so.Id] = smp.Poses.Values.First() };
                demo.Goal.ObjectId = so.Id;
                _demos.Add((snap, demo));
                j.Value = final;
                RhinoDoc.ActiveDoc.Objects.FindId(_target).Attributes.SetUserString("tinker_joint", JsonSerializer.Serialize(j));
                _status.Text = $"recorded demonstration {_demos.Count}";
            }
            catch (InvalidOperationException ex) { _status.Text = ex.Message; }
        }

        async Task Learn()
        {
            if (_demos.Count == 0) { _status.Text = "record a demonstration first"; return; }
            _status.Text = "learning..."; _progress.Indeterminate = true;
            try
            {
                var name = "rhino-" + _demos[0].demo.Goal.ObjectId.ToLowerInvariant();
                var res = await Task.Run(() => Client().LearnAsync(_demos[0].scene, _demos.Select(d => d.demo).ToList(), name.Length > 60 ? name.Substring(0, 60) : name));
                var skill = res.RootElement.GetProperty("skill");
                _skill = skill.GetProperty("name").GetString();
                _status.Text = $"learned {_skill}; confidence {skill.GetProperty("evaluation").GetProperty("confidence").GetDouble():0.00} (heuristic)";
            }
            catch (Exception ex) { _status.Text = "learn failed: " + ex.Message; }
            finally { _progress.Indeterminate = false; }
        }

        async Task Simulate()
        {
            var so = Target(out var snap);
            if (so == null || _skill == null) { _status.Text = "learn a skill first"; return; }
            var j = so.Joints[0];
            var goal = j.Kind == "revolute" ? _goal.Value * Math.PI / 180 : _goal.Value;
            _status.Text = "simulating..."; _progress.Indeterminate = true;
            try
            {
                _plan = await Task.Run(() => Client().PlanAsync(snap, _skill, so.Id, j.Name, goal));
                var sim = _plan.RootElement.GetProperty("simulation");
                _status.Text = sim.GetProperty("success").GetBoolean() ? "simulation passed" :
                    "simulation failed: " + string.Join("; ", sim.GetProperty("violations").EnumerateArray().Select(v => v.GetProperty("code").GetString()));
            }
            catch (Exception ex) { _status.Text = "simulate failed: " + ex.Message; }
            finally { _progress.Indeterminate = false; }
        }

        void Preview()
        {
            if (_plan == null || !_plan.RootElement.GetProperty("simulation").GetProperty("success").GetBoolean()) { _status.Text = "simulate first"; return; }
            var so = Target(out _)!;
            var last = _plan.RootElement.GetProperty("preview").EnumerateArray().Last().GetProperty("pose");
            var pose = JsonSerializer.Deserialize<Pose>(last.GetRawText())!;
            var o = RhinoDoc.ActiveDoc.Objects.FindId(_target);
            var g = o.Geometry.Duplicate();
            g.Transform(RhinoConnector.Between(so.Pose, pose));
            _conduit ??= new PreviewConduit();
            _conduit.Ghosts.Clear(); _conduit.Ghosts.Add(g); _conduit.Enabled = true;
            RhinoDoc.ActiveDoc.Views.Redraw();
            _status.Text = "previewing (document unchanged). Apply or Undo";
        }

        void Apply()
        {
            if (_conduit == null || _conduit.Ghosts.Count == 0) { _status.Text = "preview first: tingle never auto-applies"; return; }
            if (Rhino.UI.Dialogs.ShowMessage("Apply the simulated move?", "tingle", Rhino.UI.ShowMessageButton.YesNo, Rhino.UI.ShowMessageIcon.Question) != Rhino.UI.ShowMessageResult.Yes) return;
            var so = Target(out _)!;
            var final = _plan!.RootElement.GetProperty("preview").EnumerateArray().Last().GetProperty("value").GetDouble();
            RhinoApp.InvokeOnUiThread(new Action(() =>
            {
                _undoSerial = RhinoConnector.ApplyJoint(RhinoDoc.ActiveDoc, RhinoDoc.ActiveDoc.Objects.FindId(_target), so, so.Joints[0], final);
                _conduit.Enabled = false; _conduit.Ghosts.Clear();
                _status.Text = "applied (Undo reverts it as one step)";
            }));
        }
    }
}
