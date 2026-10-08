"""Houdini test: 1M points on pighead + pnoise, rendered as a volume in Solaris/Karma.

Run in Houdini's Python Shell, or:  hython houdini_pighead_points_volume.py [out.hip]

SOP chain (/obj/pighead_pts):
    pighead -> scatter (1M) -> wrangle (pnoise -> Cd / pscale / density)
            -> volumerasterizeparticles (density VDB) -> OUT
LOP chain (/stage):
    sopimport (OUT) -> camera -> dome light -> karmarenderproperties -> usdrender
"""
import sys

import hou

NPTS = 1_000_000

WRANGLE = r"""
// pnoise test: animated 3D periodic noise driving color and density
float freq = chf("freq");
vector pos = @P * freq + {0, 1, 0} * @Time * chf("speed");
float n = pnoise(pos, {10, 10, 10});            // -1..1
n = fit(n, -0.7, 0.7, 0, 1);
f@density = n;
@pscale   = chf("base_pscale") * (0.5 + n);
v@Cd      = chramp("color", n);
"""


def _node_type(category, *names):
    for n in names:
        if category.nodeTypes().get(n):
            return n
    raise RuntimeError("none of %s found" % (names,))


def build_sops(obj):
    geo = obj.createNode("geo", "pighead_pts")
    sops = hou.sopNodeTypeCategory()

    pig = geo.createNode(_node_type(sops, "testgeometry_pighead"), "pighead")

    scatter = geo.createNode("scatter::2.0" if sops.nodeTypes().get("scatter::2.0") else "scatter", "scatter_1M")
    scatter.setInput(0, pig)
    scatter.parm("npts").set(NPTS)

    wrangle = geo.createNode("attribwrangle", "pnoise")
    wrangle.setInput(0, scatter)
    wrangle.parm("snippet").set(WRANGLE)
    # spare parms for the channels used above
    ptg = wrangle.parmTemplateGroup()
    ptg.append(hou.FloatParmTemplate("freq", "Freq", 1, default_value=(3.0,)))
    ptg.append(hou.FloatParmTemplate("speed", "Speed", 1, default_value=(0.5,)))
    ptg.append(hou.FloatParmTemplate("base_pscale", "Base Pscale", 1, default_value=(0.01,)))
    ptg.append(hou.RampParmTemplate("color", "Color", hou.rampParmType.Color))
    wrangle.setParmTemplateGroup(ptg)

    # points -> density VDB (this is what makes "points render as volume" in Karma)
    rast = geo.createNode(_node_type(sops, "volumerasterizeparticles", "volumerasterizeparticles::2.0"), "points_to_volume")
    rast.setInput(0, wrangle)
    for name, val in (("voxelsize", 0.01), ("particlescale", 1.5)):
        p = rast.parm(name)
        if p:
            p.set(val)

    out = geo.createNode("null", "OUT")
    out.setInput(0, rast)
    out.setDisplayFlag(True)
    out.setRenderFlag(True)
    geo.layoutChildren()
    return out


def build_lops(stage, sop_out):
    imp = stage.createNode("sopimport", "pighead_volume")
    imp.parm("soppath").set(sop_out.path())

    cam = stage.createNode("camera", "cam1")
    cam.parmTuple("t").set((0, 0.6, 5))
    cam.setInput(0, imp)

    dome = stage.createNode("domelight::2.0" if hou.lopNodeTypeCategory().nodeTypes().get("domelight::2.0") else "domelight", "dome")
    dome.setInput(0, cam)

    props = stage.createNode("karmarenderproperties", "karma_props")
    props.setInput(0, dome)
    props.parm("camera").set("/cameras/cam1")
    for name, val in (("samplesperpixel", 16), ("resolutionx", 1280), ("resolutiony", 720)):
        p = props.parm(name)
        if p:
            p.set(val)

    rop = stage.createNode("usdrender_rop", "render")
    rop.setInput(0, props)
    stage.layoutChildren()
    return rop


def main():
    obj = hou.node("/obj")
    stage = hou.node("/stage")
    sop_out = build_sops(obj)
    rop = build_lops(stage, sop_out)
    rop.setDisplayFlag(True) if hasattr(rop, "setDisplayFlag") else None
    print("Built:", sop_out.path(), "->", rop.path())
    if len(sys.argv) > 1:
        hou.hipFile.save(sys.argv[1])
        print("Saved", sys.argv[1])


main()
