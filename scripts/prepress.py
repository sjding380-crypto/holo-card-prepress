"""Source-faithful foil-card annotation and design-master export; not a segmenter."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import sys
from PIL import Image, ImageChops, ImageDraw, ImageFont, ImageOps, ImageCms
from io import BytesIO


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def write_json(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def source_image(path):
    with Image.open(path) as raw:
        if raw.mode not in ("RGB", "RGBA"):
            raise ValueError("Source must be RGB/RGBA; convert CMYK or grayscale with correct color management first / 请先正确转换色彩模式并保留原文件")
        icc = raw.info.get("icc_profile")
        if icc:
            try:
                profile = ImageCms.ImageCmsProfile(BytesIO(icc))
                if profile.profile.xcolor_space.strip() != "RGB":
                    raise ValueError("Source pixels and ICC disagree; an RGB ICC is required")
            except (OSError, ImageCms.PyCMSError) as e:
                raise ValueError("Invalid source ICC profile; check color management first") from e
        im = ImageOps.exif_transpose(raw).convert("RGBA")
    return im, icc


def font(size):
    for p in ["C:/Windows/Fonts/msyh.ttc", "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc", "/System/Library/Fonts/PingFang.ttc"]:
        if Path(p).is_file():
            return ImageFont.truetype(p, size)
    return ImageFont.load_default(size=size)


def wrap(text, draw, face, width):
    lines, line = [], ""
    for char in str(text):
        if char == "\n" or (line and draw.textlength(line + char, font=face) > width):
            lines.append(line)
            line = "" if char == "\n" else char
        else:
            line += char
    return lines + ([line] if line else [])


def validate_plan(plan, size):
    elements = plan.get("elements")
    if not isinstance(elements, list) or not elements:
        raise ValueError("Plan needs elements")
    ids = set()
    for e in elements:
        eid = e.get("id", "")
        if not isinstance(eid, str) or not re.fullmatch(r"[FP][0-9]{2,}", eid) or eid in ids:
            raise ValueError("IDs must be unique F01/P01 identifiers")
        ids.add(eid)
        if e.get("treatment") not in ("foil", "protect") or eid[0] != ("F" if e["treatment"] == "foil" else "P"):
            raise ValueError("ID and treatment disagree")
        if not e.get("label") or not e.get("reason") or len(e.get("polygon", [])) < 3:
            raise ValueError("Each element needs label, reason and polygon")
        for p in e["polygon"]:
            if (len(p) != 2 or not all(isinstance(n, (int, float)) for n in p)
                    or not (0 <= p[0] < size[0] and 0 <= p[1] < size[1])):
                raise ValueError("Polygon outside source image")
    return elements


def annotation_image(im, elements):
    scale = min(1, 1300 / im.width, 1600 / im.height)
    w, h = max(1, round(im.width * scale)), max(1, round(im.height * scale))
    face, small = font(23), font(19)
    measure = ImageDraw.Draw(Image.new("RGB", (1, 1)))
    blocks = [(e, wrap(e["label"], measure, face, 410), wrap(e["reason"], measure, small, 410)) for e in elements]
    height = max(h, 250 + sum(72 + len(a) * 32 + len(b) * 28 for _, a, b in blocks))
    canvas = Image.new("RGBA", (w + 460, height), "#121a27")
    base = Image.new("RGBA", (w, h), "#eeeeee")
    base.alpha_composite(im.resize((w, h), Image.Resampling.LANCZOS))
    canvas.alpha_composite(base)
    overlay = Image.new("RGBA", canvas.size)
    draw = ImageDraw.Draw(overlay)
    for e in elements:
        color = (36, 194, 255) if e["treatment"] == "foil" else (87, 220, 151)
        points = [(round(x * scale), round(y * scale)) for x, y in e["polygon"]]
        draw.polygon(points, fill=(*color, 40), outline=(*color, 255), width=3)
    canvas = Image.alpha_composite(canvas, overlay)
    draw = ImageDraw.Draw(canvas)
    for e in elements:
        x = min(max(0, round(min(p[0] for p in e["polygon"]) * scale)), max(0, w - 65))
        y = max(0, round(min(p[1] for p in e["polygon"]) * scale) - 30)
        draw.rectangle((x, y, x + 63, y + 28), fill="#102030")
        draw.text((x + 6, y), e["id"], font=small, fill="white")
    x, y = w + 24, 22
    for text in ["局部闪卡 · 元素确认", "蓝色 F：建议发闪", "绿色 P：保留白墨", "未编号区域默认保留白墨"]:
        draw.text((x, y), text, font=face, fill="white")
        y += 36
    y += 20
    for e, labels, reasons in blocks:
        draw.text((x, y), e["id"], font=face, fill="#24c2ff" if e["treatment"] == "foil" else "#57dc97")
        y += 34
        for line in labels:
            draw.text((x, y), line, font=face, fill="white")
            y += 32
        for line in reasons:
            draw.text((x, y), line, font=small, fill="#cbd5e1")
            y += 28
        y += 34
    draw.text((x, y), "范围示意，确认后再精抠。", font=small, fill="#fbbf24")
    return canvas.convert("RGB")


def annotate(source, plan_path, out):
    source, plan_path, out = Path(source).resolve(), Path(plan_path).resolve(), Path(out).resolve()
    im, _ = source_image(source)
    elements = validate_plan(read_json(plan_path), im.size)
    if source in [out / n for n in ("01_annotation.png", "plan_review.md", "plan_manifest.json")]:
        raise ValueError("Output would overwrite source")
    preview = annotation_image(im, elements)
    out.mkdir(parents=True, exist_ok=True)
    preview.save(out / "01_annotation.png")
    record = {"source": str(source), "plan": str(plan_path), "source_sha256": digest(source),
              "plan_sha256": digest(plan_path), "normalized_size_px": list(im.size)}
    write_json(out / "plan_manifest.json", record)
    lines = ["# 元素确认", "", "未编号区域默认保留白墨；确认后再精抠。", ""]
    lines += [f"- {e['id']} {e['label']} / {e['treatment']}：{e['reason']}" for e in elements]
    (out / "plan_review.md").write_text("\n".join(lines), encoding="utf-8")
    return record


def current_job(out):
    out = Path(out).resolve()
    r = read_json(out / "plan_manifest.json")
    if any(digest(r[key]) != r[key + "_sha256"] for key in ("source", "plan")):
        raise ValueError("Source or plan changed / 原图或方案变化，旧确认失效")
    im, icc = source_image(r["source"])
    elements = validate_plan(read_json(r["plan"]), im.size)
    return out, r, im, icc, elements


def approve(out, ids, evidence):
    out, r, _, _, elements = current_job(out)
    allowed = {e["id"] for e in elements if e["treatment"] == "foil"}
    if len(set(ids)) != len(ids) or not set(ids) <= allowed:
        raise ValueError("Only proposed foil IDs can be approved")
    if not str(evidence).strip():
        raise ValueError("Actual user confirmation required / 请记录用户确认")
    r = {k: r[k] for k in ("source_sha256", "plan_sha256")}
    r.update(foil_ids=list(ids), user_evidence=evidence)
    write_json(out / "approved.json", r)
    return r


def export(out, mask_dir):
    out, r, im, icc, elements = current_job(out)
    if not (out / "approved.json").is_file():
        raise ValueError("User confirmation required / 缺用户确认")
    a = read_json(out / "approved.json")
    if any(a.get(k) != r[k] for k in ("source_sha256", "plan_sha256")):
        raise ValueError("Plan changed / 方案变化，旧确认失效")
    ids = a.get("foil_ids", [])
    allowed = {e["id"] for e in elements if e["treatment"] == "foil"}
    if len(set(ids)) != len(ids) or not set(ids) <= allowed or not a.get("user_evidence"):
        raise ValueError("Invalid confirmation record")
    delivery = out / "delivery"
    if delivery.exists():
        raise ValueError("delivery exists; use a new versioned job directory")
    union, masks, hashes = Image.new("L", im.size, 0), {}, {}
    for eid in ids:
        p = Path(mask_dir) / (eid + ".png")
        if not p.is_file():
            raise ValueError(f"Final mask missing / 缺精细蒙版: {eid}")
        with Image.open(p) as raw:
            if raw.size != im.size:
                raise ValueError(f"Mask size mismatch / 蒙版尺寸错误: {eid}")
            if raw.mode not in ("L", "1"):
                raise ValueError("Mask must be L or 1, white=foil")
            masks[eid] = raw.convert("L")
        if masks[eid].getbbox() is None:
            raise ValueError("Approved foil mask is empty")
        union = ImageChops.lighter(union, masks[eid])
        hashes[eid] = digest(p)
    alpha = im.getchannel("A")
    foil = ImageChops.multiply(union, alpha)
    white = Image.new("RGBA", im.size, "white")
    white.putalpha(ImageChops.multiply(ImageOps.invert(union), alpha))
    check = Image.new("RGBA", im.size, "#777777")
    check.alpha_composite(white)
    registration = Image.new("RGBA", im.size, "#eeeeee")
    registration.alpha_composite(im)
    tint = Image.new("RGBA", im.size, (36, 194, 255, 0))
    tint.putalpha(foil.point(lambda p: round(p * .4)))
    registration.alpha_composite(tint)
    delivery.mkdir()
    (delivery / "cutouts").mkdir()
    options = {"icc_profile": icc} if icc else {}
    im.save(delivery / "01_color.png", **options)
    white.save(delivery / "02_white_ink_rgba.png")
    foil.save(delivery / "03_foil_mask_review.png")
    check.convert("RGB").save(delivery / "04_white_ink_check.png")
    registration.convert("RGB").save(delivery / "05_registration_check.png")
    for eid, mask in masks.items():
        cutout = im.copy()
        cutout.putalpha(ImageChops.multiply(mask, alpha))
        cutout.save(delivery / "cutouts" / f"{eid}_color.png", **options)
    result = {"status": "draft_awaiting_user_proof_review", "size_px": list(im.size),
              "source_sha256": r["source_sha256"], "plan_sha256": r["plan_sha256"],
              "approved_foil_ids": ids, "mask_sha256": hashes, "physical_size_mm": None,
              "white_ink": "white RGB; alpha=white coverage; transparent=no white ink",
              "foil_review": "white=foil, NOT the printer white-ink plate", "resampled": False}
    write_json(delivery / "delivery_manifest.json", result)
    (delivery / "delivery_notes.md").write_text(
        "# 设计母版，待用户确认效果及厂家规格核对\n\n"
        "01_color.png：完整彩色图。02_white_ink_rgba.png：白墨覆盖版，透明=不印白墨。\n"
        "03 白形=发闪，不能直接当白墨版；04/05 是检查附件，不能印刷。\n"
        "镭射底材是实物。尚未指定尺寸、出血、安全区、ICC、白墨专色格式及覆膜。\n"
        "没有假定物理尺寸或虚构 DPI。套位预览不模拟真实反光。\n", encoding="utf-8")
    return result


def delivery_fingerprint(delivery):
    files = {str(p.relative_to(delivery)): digest(p)
             for p in sorted(delivery.rglob('*')) if p.is_file()}
    return hashlib.sha256(json.dumps(files, sort_keys=True).encode()).hexdigest()


def review(out, stage, decision, evidence):
    """Record review against actual delivered bytes; this does not establish user intent."""
    out, r, _, _, _ = current_job(out)
    if stage not in ("proof", "final") or decision not in ("approve", "revise") or not evidence.strip():
        raise ValueError("Invalid review / 请提供真实用户反馈")
    delivery = out / "delivery"
    if not delivery.is_dir():
        raise ValueError("No proof to review")
    fingerprint = delivery_fingerprint(delivery)
    if stage == "final" and decision == "approve":
        p = out / "review_proof.json"
        proof = read_json(p) if p.exists() else {}
        if (proof.get("decision") != "approve" or proof.get("delivery_sha256") != fingerprint
                or any(proof.get(k) != r[k] for k in ("source_sha256", "plan_sha256"))):
            raise ValueError("Approve current proof first / 当前效果版尚未确认或已变化")
    result = {"stage": stage, "decision": decision, "user_evidence": evidence,
              "delivery_sha256": fingerprint, "plan_sha256": r["plan_sha256"],
              "source_sha256": r["source_sha256"]}
    write_json(out / f"review_{stage}.json", result)
    return result


def package(out):
    """Copy only the approved production images; keep all review artifacts internal."""
    out, r, _, _, _ = current_job(out)
    delivery, final = out / 'delivery', out / 'final'
    if final.exists():
        raise ValueError('final exists; use a new versioned job directory')
    if not delivery.is_dir():
        raise ValueError('No delivery to package')
    fingerprint = delivery_fingerprint(delivery)
    for stage in ('proof', 'final'):
        path = out / f'review_{stage}.json'
        record = read_json(path) if path.is_file() else {}
        if record.get('decision') != 'approve':
            raise ValueError(f'Current {stage} approval required / 缺当前效果或定稿确认')
        if (record.get('delivery_sha256') != fingerprint
                or any(record.get(k) != r[k] for k in ('source_sha256', 'plan_sha256'))):
            raise ValueError('Delivery changed / 文件变化，请重新确认')
    names = ['01_color.png', '02_white_ink_rgba.png']
    if (delivery / '03_varnish.png').is_file():
        names.append('03_varnish.png')
    sizes = []
    for name in names:
        with Image.open(delivery / name) as im:
            if im.format != 'PNG':
                raise ValueError('Production images must be actual PNG files')
            sizes.append(im.size)
            im.verify()
    if len(set(sizes)) != 1:
        raise ValueError('Production image size mismatch / 生产图尺寸不一致')
    final.mkdir()
    for name in names:
        shutil.copyfile(delivery / name, final / name)
    return {'files': [str(final / name) for name in names], 'count': len(names)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    subs = parser.add_subparsers(dest="command", required=True)
    a = subs.add_parser("annotate")
    for key in ("source", "plan", "out"):
        a.add_argument("--" + key, required=True, type=Path)
    a = subs.add_parser("approve")
    a.add_argument("--out", required=True, type=Path)
    a.add_argument("--ids", nargs="*", required=True)
    a.add_argument("--evidence", required=True)
    a = subs.add_parser("export")
    a.add_argument("--out", required=True, type=Path)
    a.add_argument("--mask-dir", required=True, type=Path)
    a = subs.add_parser("review")
    a.add_argument("--out", required=True, type=Path)
    a.add_argument("--stage", choices=["proof", "final"], required=True)
    a.add_argument("--decision", choices=["approve", "revise"], required=True)
    a.add_argument("--evidence", required=True)
    a = subs.add_parser("package")
    a.add_argument("--out", required=True, type=Path)
    args = vars(parser.parse_args())
    command = args.pop("command")
    if command == "annotate":
        args["plan_path"] = args.pop("plan")
    try:
        print(json.dumps(globals()[command](**args), ensure_ascii=False, indent=2))
    except (ValueError, OSError, KeyError) as e:
        print(str(e), file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    sys.exit(main())
