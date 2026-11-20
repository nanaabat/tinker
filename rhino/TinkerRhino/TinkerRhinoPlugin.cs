using System;
using System.Runtime.InteropServices;
using Rhino;
using Rhino.PlugIns;
using Rhino.UI;

[assembly: Guid("6b7d2f0e-3c1a-4f7e-9a2b-5d4e8c1f0a11")]
[assembly: PlugInDescription(DescriptionType.Organization, "AprewaTurkson Inc.")]

namespace TinkerRhino
{
    public sealed class TinkerRhinoPlugin : PlugIn
    {
        public static TinkerRhinoPlugin? Instance { get; private set; }
        public TinkerRhinoPlugin() { Instance = this; }
        public override PlugInLoadTime LoadTime => PlugInLoadTime.AtStartup;

        protected override LoadReturnCode OnLoad(ref string errorMessage)
        {
            // dockable Eto panel, opened from the Panels menu or the TinglePanel command
            Panels.RegisterPanel(this, typeof(TinkerPanel), "tingle", null);
            return LoadReturnCode.Success;
        }
    }
}
