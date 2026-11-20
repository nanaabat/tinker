using System;
using System.Collections.Generic;
using System.Linq;
using System.Text.Json;
using Rhino;
using Rhino.DocObjects;
using Rhino.Geometry;
using TinkerWink.Contracts;
using TinkerWink.Core;

namespace TinkerRhino
{
    /// <summary>Rhino side of the connector interface. Objects opt in with user strings:
    /// tinker_type (wall, blind, sliding_panel, ...), tinker_joint (JSON Joint), tinker_id (optional stable id).
    /// All document edits go through RhinoDoc on the UI thread with an undo record.</summary>
    public static class RhinoConnector
    {
        public static string Units(RhinoDoc doc) => doc.ModelUnitSystem switch
        {
            UnitSystem.Millimeters => "mm", UnitSystem.Centimeters => "cm", UnitSystem.Meters => "m",
            UnitSystem.Inches => "in", UnitSystem.Feet => "ft", _ => "m",
        };

        public static Pose PoseOf(RhinoObject o, out double[] size)
        {
            // oriented frame: object's stored plane (tinker_frame) if present, else world-aligned bounding box
            var bb = o.Geometry.GetBoundingBox(true);
            var c = bb.Center;
            size = new[] { bb.Max.X - bb.Min.X, bb.Max.Y - bb.Min.Y, bb.Max.Z - bb.Min.Z };
            var q = new[] { 1.0, 0, 0, 0 };
            var frame = o.Attributes.GetUserString("tinker_frame");
            if (!string.IsNullOrEmpty(frame))
            {
                var f = JsonSerializer.Deserialize<FrameRecord>(frame)!;
                q = f.Rotation; size = f.Size; c = new Point3d(f.Center[0], f.Center[1], f.Center[2]);
            }
            return new Pose { Position = new List<double> { c.X, c.Y, c.Z }, Rotation = new List<double>(q) };
        }

        public sealed class FrameRecord
        {
            public double[] Center { get; set; } = new double[3];
            public double[] Rotation { get; set; } = { 1, 0, 0, 0 };
            public double[] Size { get; set; } = new double[3];
        }

        public static SceneSnapshot Snapshot(RhinoDoc doc)
        {
            var objs = new List<SceneObject>();
            foreach (var o in doc.Objects.Where(x => !string.IsNullOrEmpty(x.Attributes.GetUserString("tinker_type"))))
            {
                var pose = PoseOf(o, out var size);
                var joints = new List<Joint>();
                var js = o.Attributes.GetUserString("tinker_joint");
                if (!string.IsNullOrEmpty(js)) joints.Add(JsonSerializer.Deserialize<Joint>(js)!);
                var id = o.Attributes.GetUserString("tinker_id");
                objs.Add(new SceneObject
                {
                    Id = string.IsNullOrEmpty(id) ? "obj-" + o.Id.ToString("N").Substring(0, 20) : id, HostId = o.Id.ToString(),
                    Name = string.IsNullOrEmpty(o.Name) ? o.Id.ToString() : o.Name, Type = o.Attributes.GetUserString("tinker_type"),
                    ParentId = null, Pose = pose, Size = size.ToList(), GeometryRef = "rhino:" + o.ObjectType,
                    Collision = o.Attributes.GetUserString("tinker_collision") != "false", Joints = joints,
                });
            }
            return new SceneSnapshot
            {
                SchemaVersion = SchemaInfo.Version, SceneId = "rhino-" + (doc.Name ?? "untitled").Replace(' ', '-'),
                Units = Units(doc), CoordinateSystem = new SceneSnapshotCoordinateSystem { Up = "z", Handedness = "right" },
                Host = new SceneSnapshotHost { Name = "rhino", Version = RhinoApp.Version.ToString() }, Objects = objs, Constraints = new List<Constraint>(),
            };
        }

        /// <summary>Rigid transform taking pose a to pose b.</summary>
        public static Transform Between(Pose a, Pose b)
        {
            Transform ToWorld(Pose p)
            {
                var q = new Quaternion(p.Rotation[0], p.Rotation[1], p.Rotation[2], p.Rotation[3]);
                q.GetRotation(out Transform r);
                return Transform.Translation(p.Position[0], p.Position[1], p.Position[2]) * r;
            }
            var ta = ToWorld(a);
            ta.TryGetInverse(out var inv);
            return ToWorld(b) * inv;
        }

        /// <summary>Apply a joint move as ONE undo record. Returns the undo record serial.</summary>
        public static uint ApplyJoint(RhinoDoc doc, RhinoObject o, SceneObject so, Joint j, double value)
        {
            var target = Kinematics.PoseForValue(so, j, value);
            var xf = Between(so.Pose, target);
            var sn = doc.BeginUndoRecord("tinker apply");
            try
            {
                doc.Objects.Transform(o.Id, xf, true);
                var o2 = doc.Objects.FindId(o.Id);
                j.Value = value;
                o2.Attributes.SetUserString("tinker_joint", JsonSerializer.Serialize(j));
                var frame = o2.Attributes.GetUserString("tinker_frame");
                if (!string.IsNullOrEmpty(frame))
                {
                    var f = JsonSerializer.Deserialize<FrameRecord>(frame)!;
                    f.Center = target.Position.ToArray(); f.Rotation = target.Rotation.ToArray();
                    o2.Attributes.SetUserString("tinker_frame", JsonSerializer.Serialize(f));
                }
                o2.CommitChanges();
            }
            finally { doc.EndUndoRecord(sn); }
            doc.Views.Redraw();
            return sn;
        }
    }
}
