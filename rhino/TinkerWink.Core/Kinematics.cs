// Port of packages/scene-core/tw_scene (quat.py, kinematics.py). Parity is checked against Python-generated vectors.
using System;
using System.Collections.Generic;
using TinkerWink.Contracts;

namespace TinkerWink.Core
{
    public static class Quat
    {
        public static double[] Mul(double[] a, double[] b) => new[]
        {
            a[0]*b[0] - a[1]*b[1] - a[2]*b[2] - a[3]*b[3],
            a[0]*b[1] + a[1]*b[0] + a[2]*b[3] - a[3]*b[2],
            a[0]*b[2] - a[1]*b[3] + a[2]*b[0] + a[3]*b[1],
            a[0]*b[3] + a[1]*b[2] - a[2]*b[1] + a[3]*b[0],
        };
        public static double[] Conj(double[] q) => new[] { q[0], -q[1], -q[2], -q[3] };
        public static double[] Rotate(double[] q, double[] v)
        {
            var p = Mul(Mul(q, new[] { 0.0, v[0], v[1], v[2] }), Conj(q));
            return new[] { p[1], p[2], p[3] };
        }
        public static double[] FromAxisAngle(double[] axis, double angle)
        {
            var n = Math.Sqrt(axis[0]*axis[0] + axis[1]*axis[1] + axis[2]*axis[2]);
            if (n == 0) n = 1;
            var s = Math.Sin(angle / 2);
            return new[] { Math.Cos(angle / 2), axis[0]/n*s, axis[1]/n*s, axis[2]/n*s };
        }
        public static double AngleAbout(double[] q, double[] axis)
        {
            var n = Math.Sqrt(axis[0]*axis[0] + axis[1]*axis[1] + axis[2]*axis[2]);
            if (n == 0) n = 1;
            var proj = (q[1]*axis[0] + q[2]*axis[1] + q[3]*axis[2]) / n;
            var ang = 2 * Math.Atan2(proj, q[0]);
            if (ang > Math.PI) ang -= 2 * Math.PI;
            if (ang <= -Math.PI) ang += 2 * Math.PI;
            return ang;
        }
    }

    public static class Kinematics
    {
        static double[] Add(double[] a, double[] b) => new[] { a[0]+b[0], a[1]+b[1], a[2]+b[2] };
        static double[] Sub(double[] a, double[] b) => new[] { a[0]-b[0], a[1]-b[1], a[2]-b[2] };
        static double Dot(double[] a, double[] b) => a[0]*b[0] + a[1]*b[1] + a[2]*b[2];

        public static Pose PoseForValue(SceneObject obj, Joint j, double value)
        {
            var pos = obj.Pose.Position.ToArray();
            var rot = obj.Pose.Rotation.ToArray();
            var delta = value - j.Value;
            if (j.Kind == "prismatic")
            {
                var ax = j.Axis.ToArray();
                return new Pose { Position = new List<double>(Add(pos, Quat.Rotate(rot, new[] { ax[0]*delta, ax[1]*delta, ax[2]*delta }))),
                                  Rotation = new List<double>(rot) };
            }
            var anchor = j.Anchor.ToArray();
            var anchorW = Add(pos, Quat.Rotate(rot, anchor));
            var newRot = Quat.Mul(rot, Quat.FromAxisAngle(j.Axis.ToArray(), delta));
            var newPos = Sub(anchorW, Quat.Rotate(newRot, anchor));
            return new Pose { Position = new List<double>(newPos), Rotation = new List<double>(newRot) };
        }

        public static double ValueFromPose(SceneObject obj, Joint j, Pose pose)
        {
            var pos = obj.Pose.Position.ToArray();
            var rot = obj.Pose.Rotation.ToArray();
            if (j.Kind == "prismatic")
            {
                var local = Quat.Rotate(Quat.Conj(rot), Sub(pose.Position.ToArray(), pos));
                var ax = j.Axis.ToArray();
                var n = Math.Sqrt(Dot(ax, ax));
                return j.Value + Dot(local, ax) / (n == 0 ? 1 : n);
            }
            var rel = Quat.Mul(Quat.Conj(rot), pose.Rotation.ToArray());
            return j.Value + Quat.AngleAbout(rel, j.Axis.ToArray());
        }
    }
}
