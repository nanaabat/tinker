using Rhino;
using Rhino.Commands;
using Rhino.UI;

namespace TinkerRhino
{
    public sealed class TinkerPanelCommand : Command
    {
        public override string EnglishName => "TinglePanel";
        protected override Result RunCommand(RhinoDoc doc, RunMode mode)
        {
            Panels.OpenPanel(typeof(TinkerPanel).GUID);
            return Result.Success;
        }
    }
}
