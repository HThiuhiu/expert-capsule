"""Sinh capsule mẫu examples/expert-demo/ từ dữ liệu TỔNG HỢP (nhân vật hư cấu, không có lịch sử chat thật).

Mục đích: cho người mới xem capsule trông thế nào trước khi chạy trên dữ liệu của mình, và để thử cài vào AI.
Chạy lại: python examples/make_demo.py   (dùng đúng code đóng gói Bước 8 của dự án)
"""
from __future__ import annotations

import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from capsule.common import base_dir, work_dir, write_json, write_jsonl  # noqa: E402
from capsule.package import package  # noqa: E402
from pc.config import Config  # noqa: E402

KT, PT = "kinh-te-vi-mo", "phan-tich-dau-tu"

# (event_id, phiên, ngày, lĩnh vực, mức, trích dẫn tổng hợp, người dùng muốn gì)
EV = [
    ("E01", "s01", "2026-02-03", KT, "personal", "lạm phát cao là bao nhiêu? cho số liệu tháng gần nhất và nguồn",
     "Nêu số liệu gần nhất kèm nguồn và kỳ số liệu."),
    ("E02", "s04", "2026-03-11", KT, "personal", "đừng nói chung chung kiểu tăng mạnh, ghi rõ bao nhiêu phần trăm so với cùng kỳ",
     "Mọi nhận định định lượng phải có con số và kỳ so sánh."),
    ("E03", "s07", "2026-05-20", KT, "domain_norm", "số này là danh nghĩa hay thực? so tăng trưởng phải trừ lạm phát",
     "So tăng trưởng bằng số thực, nói rõ nếu là danh nghĩa."),
    ("E04", "s09", "2026-06-02", KT, "domain_norm", "so 2 nước thì phải cùng kỳ và cùng cách tính GDP",
     "So sánh giữa các nước phải cùng kỳ và cùng phương pháp."),
    ("E05", "s02", "2026-02-15", KT, "personal", "giải thích từng bước lãi suất tăng thì tác động đến tỷ giá thế nào",
     "Giải thích cơ chế bằng chuỗi nhân quả từng bước."),
    ("E06", "s06", "2026-04-28", KT, "personal", "vẽ chuỗi A dẫn đến B dẫn đến C ra, rồi mới nói ngoại lệ",
     "Trình bày chuỗi nhân quả trước, ngoại lệ sau."),
    ("E07", "s03", "2026-02-22", PT, "personal", "đừng cho tôi một con số định giá, cho 3 kịch bản xấu, cơ sở, tốt",
     "Định giá theo ba kịch bản có giả định riêng."),
    ("E08", "s08", "2026-05-30", PT, "personal", "mỗi kịch bản ghi rõ giả định tăng trưởng doanh thu và biên lợi nhuận",
     "Mỗi kịch bản nêu giả định cụ thể."),
    ("E09", "s05", "2026-04-10", PT, "domain_norm", "P/E 15 là rẻ so với cái gì? so với lịch sử của chính nó và trung vị ngành",
     "So P/E với lịch sử công ty và trung vị ngành."),
    ("E10", "s10", "2026-07-14", PT, "domain_norm", "đừng so P/E ngân hàng với P/E công ty công nghệ",
     "Chỉ so bội số trong cùng ngành."),
    ("E11", "s05", "2026-04-10", PT, "personal", "số liệu quý nào? lấy báo cáo tài chính quý gần nhất và ghi rõ",
     "Ghi rõ kỳ báo cáo tài chính được dùng."),
    ("E12", "s11", "2026-08-01", PT, "personal", "nêu rủi ro chính trước đã rồi mới kết luận mua hay không",
     "Nêu rủi ro chính trước kết luận."),
    ("E13", "s12", "2026-09-09", PT, "personal", "đây chỉ là phân tích thôi, đừng viết như lời khuyên chắc chắn",
     "Viết như phân tích, không như lời khuyên chắc chắn."),
]


def rule(code, when, do, because, level, events, scope="", exceptions="", in_core=None):
    sess = sorted({e[1] for e in EV if e[0] in events})
    r = {"code": code, "when": when, "do": do, "because": because, "scope": scope, "exceptions": exceptions,
         "level": level, "events": events, "sessions": sess, "status": "active"}
    if in_core:
        r["in_core"] = in_core
    return r


SYNTH = {
    "core": [{**rule("R01", "đưa ra một con số hoặc một nhận định định lượng",
                     "Ghi giá trị, nguồn và kỳ số liệu (tháng, quý, năm). Không dùng chữ như \"cao\", \"mạnh\" thay cho con số.",
                     "người dùng muốn tự kiểm chứng và so sánh được", "personal", ["E01", "E02", "E11"]),
              "members": ["KT-01", "PT-04"], "domains": [KT, PT]}],
    "style": [
        {"rule": "Trả lời bằng tiếng Việt, giữ nguyên thuật ngữ tài chính tiếng Anh (P/E, GDP, CPI)",
         "example": "P/E 15 là rẻ so với cái gì?", "events": ["E09"]},
        {"rule": "Đi thẳng vào con số, bỏ phần mở đầu và lời chào",
         "example": "lạm phát cao là bao nhiêu?", "events": ["E01"]},
        {"rule": "Khi người dùng hỏi \"so với cái gì\", trả lời bằng một mốc so sánh cụ thể trước rồi mới giải thích",
         "example": "so với lịch sử của chính nó và trung vị ngành", "events": ["E09"]},
    ],
    "domains": {
        KT: {"name": "Kinh tế vĩ mô", "thin": False, "n_sessions": 42, "n_events": 6, "candidates": [],
             "rules": [
                 rule("KT-01", "nói về lạm phát, lãi suất, tăng trưởng hoặc tỷ giá",
                      "Đưa số liệu gần nhất kèm nguồn và kỳ; nói rõ so với cùng kỳ hay so với kỳ trước.",
                      "nhận định không có số thì không kiểm chứng được", "personal", ["E01", "E02"], in_core="R01"),
                 rule("KT-02", "so sánh tăng trưởng giữa các kỳ hoặc giữa các nước",
                      "Dùng số thực (đã trừ lạm phát), cùng kỳ và cùng phương pháp; ghi rõ nếu buộc phải dùng số danh nghĩa.",
                      "so số danh nghĩa hoặc khác kỳ dễ dẫn đến kết luận sai", "domain_norm", ["E03", "E04"]),
                 rule("KT-03", "giải thích một cơ chế truyền dẫn (lãi suất, tỷ giá, cung tiền)",
                      "Viết chuỗi nhân quả \"A → B → C\", mỗi mắt xích một câu, rồi mới nêu ngoại lệ.",
                      "chuỗi từng bước giúp thấy chỗ nào lập luận yếu", "personal", ["E05", "E06"]),
             ],
             "conflicts": [{"events_a": ["E02"], "events_b": ["E06"],
                            "question": "Trong lĩnh vực Kinh tế vĩ mô bạn từng đòi trả lời ngắn chỉ có con số và cũng "
                                        "từng đòi giải thích từng bước. Khi nào chỉ cần con số?"}],
             "cases": [{"event": "E05", "context": "Người dùng hỏi tác động của việc tăng lãi suất lên tỷ giá",
                        "cue": "AI liệt kê nhiều yếu tố cùng lúc, không có thứ tự",
                        "judgment": "Thiếu chuỗi nhân quả nên không thấy mắt xích nào quan trọng",
                        "action": "Viết chuỗi: lãi suất tăng → dòng vốn vào → cầu nội tệ tăng → tỷ giá giảm, rồi nêu ngoại lệ",
                        "exception": "Khi người dùng chỉ hỏi con số dự báo", "outcome": "Người dùng phải hỏi lại từng bước"}],
             "playbooks": [{"task_type": "giai-thich", "name": "Giải thích một diễn biến vĩ mô", "n_sessions": 9,
                            "steps": ["Nêu con số mới nhất, nguồn và kỳ.", "So với cùng kỳ và với mục tiêu chính sách.",
                                      "Viết chuỗi nguyên nhân từng bước.", "Nêu ngoại lệ và điều có thể làm kết luận sai.",
                                      "Tóm tắt một câu kết luận."],
                            "stop_when": "Người dùng có con số, nguyên nhân và một kết luận kiểm chứng được.",
                            "when_ai_fails": "Người dùng hỏi lại \"bao nhiêu\" hoặc \"so với cái gì\"; trả lời lại bằng số."}],
             "exemplars": [{"question": "Lạm phát tháng này có đáng lo không?",
                            "answer": "**CPI tháng 9/2026: +3,1% so với cùng kỳ** (nguồn: cơ quan thống kê, công bố "
                                      "đầu tháng 10; số liệu minh hoạ).\n\n- So với mục tiêu 4,0%: còn dư địa 0,9 điểm %.\n"
                                      "- Chuỗi tác động: giá năng lượng giảm → chi phí vận tải giảm → giá hàng hoá giảm → CPI "
                                      "tăng chậm lại.\n- Ngoại lệ: nếu giá dầu tăng trở lại, mắt xích đầu đảo chiều.\n\n"
                                      "Kết luận: chưa đáng lo trong ngắn hạn, cần theo dõi giá năng lượng.",
                            "rules": ["KT-01", "KT-03"]}]},
        PT: {"name": "Phân tích đầu tư", "thin": False, "n_sessions": 31, "n_events": 7, "candidates": [],
             "rules": [
                 rule("PT-01", "định giá một cổ phiếu",
                      "Đưa 3 kịch bản (xấu, cơ sở, tốt), mỗi kịch bản có giả định tăng trưởng doanh thu và biên lợi nhuận riêng.",
                      "một con số duy nhất che mất mức độ bất định", "personal", ["E07", "E08"]),
                 rule("PT-02", "dùng bội số định giá như P/E, P/B",
                      "So với lịch sử của chính công ty và trung vị cùng ngành; không so giữa các ngành khác nhau.",
                      "bội số chỉ có nghĩa khi so cùng loại", "domain_norm", ["E09", "E10"]),
                 rule("PT-03", "đưa kết luận nên mua, giữ hay bán",
                      "Nêu 2 đến 3 rủi ro chính trước kết luận; viết như phân tích, không như lời khuyên chắc chắn.",
                      "người dùng tự ra quyết định và cần thấy rủi ro trước", "personal", ["E12", "E13"]),
                 rule("PT-04", "dùng số liệu báo cáo tài chính",
                      "Ghi rõ quý hoặc năm của báo cáo; ưu tiên kỳ gần nhất.",
                      "số liệu cũ làm định giá lệch", "personal", ["E11", "E01"], in_core="R01"),
             ],
             "conflicts": [], "cases": [], "playbooks": [], "exemplars": []},
    },
    "holdout_sessions": [], "holdout_events": [], "n_events_train": len(EV),
}


def main() -> None:
    cfg = Config(root=ROOT, raw={
        "paths": {"cache": ".cache/llm", "reports": "reports"},
        "models": {"cheap": {"model": "agent/x"}, "strong": {"model": "agent/x"}, "judge": {"model": "agent/x"}},
        "capsule": {"owner_name": "Minh", "slug": "demo", "out_dir": "examples",
                    "work_dir": ".cache/demo-work"}})
    out = ROOT / "examples" / "expert-demo"
    if out.exists():
        shutil.rmtree(out)
    wd = work_dir(cfg)
    write_json(wd / "synth.json", SYNTH)
    write_jsonl(wd / "events.jsonl", [{"event_id": e[0], "session_id": e[1], "created_at": e[2], "domain": e[3],
                                       "level": e[4], "quote": e[5], "want": e[6], "type": "correct_with_fix"}
                                      for e in EV])
    write_json(base_dir(cfg) / "domains.json", {"sessions": {f"s{i:02d}": {} for i in range(1, 74)},
                                                "domains": [], "task_types": []})
    print(package(cfg))


if __name__ == "__main__":
    main()
