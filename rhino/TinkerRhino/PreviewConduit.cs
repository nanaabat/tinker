using System.Collections.Generic;
using System.Drawing;
using Rhino.Display;
using Rhino.Geometry;

namespace TinkerRhino
{
    /// <summary>Non-destructive preview: draws the moved geometry as a ghost; the document is not modified.</summary>
    public sealed class PreviewConduit : DisplayConduit
    {
        public List<GeometryBase> Ghosts { get; } = new List<GeometryBase>();
        protected override void CalculateBoundingBox(CalculateBoundingBoxEventArgs e)
        {
            foreach (var g in Ghosts) e.IncludeBoundingBox(g.GetBoundingBox(false));
        }
        protected override void PostDrawObjects(DrawEventArgs e)
        {
            foreach (var g in Ghosts)
            {
                switch (g)
                {
                    case Brep b: e.Display.DrawBrepWires(b, Color.FromArgb(230, 120, 40), 1); break;
                    case Mesh m: e.Display.DrawMeshWires(m, Color.FromArgb(230, 120, 40)); break;
                    case Extrusion x: e.Display.DrawBrepWires(x.ToBrep(), Color.FromArgb(230, 120, 40), 1); break;
                }
            }
        }
    }
}
