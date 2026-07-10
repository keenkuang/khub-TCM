# 文档版本 Diff 第 2 轮代码评审（R1 修复验证）

评审提交：0de43a0（分支 m1）

R1 报告：`docs/review_diff_r1.md`（提交 c522c54）

R1 修复范围：仅 `khub/api.py`，10 行新增

---

## 1. R1 修复验证

R1 识别了 3 个待修复问题（F1 高优先，F2/F3 中优先）和 4 个建议（S1-S4）。本轮审核 0de43a0 中完成的修复：

### 1.1 F2 + F3：5000 行上限（`api.py` 第 211–216 行）

**原始问题：** `diff_lines` 构建 `(m+1)×(n+1)` DP 表，O(mn) 内存。无截断时大文档（10k × 10k）需 ~2.8 GB。

**修复代码：**
```python
c1_lines = (ver1["content"] or "").splitlines()
c2_lines = (ver2["content"] or "").splitlines()
if len(c1_lines) > 5000 or len(c2_lines) > 5000:
    return 413, {"error": "文档过大，无法比较（超过 5000 行上限）"}
c1 = "\n".join(c1_lines)
c2 = "\n".join(c2_lines)
diff = diff_lines(c1, c2)
```

**验证结果：✅ 修复有效，存在轻微副作用**

| 方面 | 结论 |
|------|------|
| 边界正确性 | `splitlines()` 计数与 `diff_lines` 内部 `splitlines(keepends=True)` 计数一致 |
| 空内容 | `"".splitlines()` → `[]`, `"\n".join([])` → `""`, `diff_lines("","")` → `[]` |
| 5000 行正常通过 | 已验证 ✓ |
| 5001 行拒绝 | `len(lines) > 5000` 为 True, 413 返回 |
| 状态码 | 413 Payload Too Large — 语义正确 |
| NPE 防护 | `ver1["content"] or ""` 处理 None 内容 |
| 同时超限 | 其中任一超限即拒绝，保守但安全 |
| `v1<0` → `v1=0`（受拒）| `_safe_int("-1", 0)` = -1, `-1 < 0` True ✓ |

**⚠️ 副作用：内容归一化**

修复使用 `splitlines()`（不带 `keepends=True`）+ `"\n".join()` 重组字符串：

- 原始行为：`diff_lines(ver1["content"], ver2["content"])`
- 修复后：先 split / 再 join 再传入 `diff_lines`

差异：
1. **尾部换行符被移除**：`"a\nb\n".splitlines()` → `["a","b"]` → `"\n".join(...)` → `"a\nb"`（失去尾部空行）
2. **`\r\n` → `\n` 归一化**：`"a\r\nb".splitlines()` → `["a","b"]` → `"\n".join(...)` → `"a\nb"`

两个版本经历相同的变换，所以 diff 结果对相同内容仍为全 equal。尾部换行符差异不会触发误报 diff。对于医疗文档场景，尾部换行符无语义影响。此副作用可接受。

### 1.2 S1：负数 version_id 拒绝（`api.py` 第 204 行）

**原始问题：** `not v1 or not v2` 不拒绝负数，语义不够精确。

**修复代码：**
```python
if not v1 or not v2 or v1 < 0 or v2 < 0:
```

**验证结果：✅ 功能正确，写法冗余**

| 输入 | `not v1` | `v1 < 0` | 综合结果 |
|------|----------|----------|----------|
| `v1=0`（缺失） | True | — | 400 ✓ |
| `v1=-1` | False（-1 为 truthy） | True | 400 ✓ |
| `v1=42` | False | False | 通过 ✓ |

`_safe_int` 的 `int(value)` 天然支持负数字符串 → `int("-1")` = -1，和 `_safe_int` 的异常处理不冲突。✅

**琐事（不需要修）：** `not v1 or not v2 or v1 < 0 or v2 < 0` 等价于 `v1 <= 0 or v2 <= 0`。功能等价，清晰度相同，无需额外改动。

---

## 2. R1 未修复项

| 编号 | 问题 | R1 严重性 | 当前状态 |
|------|------|-----------|----------|
| **F1** | `script.js` 中 `esc()` 在 onclick 中的 XSS 逃逸 | **高** | ❌ **未修复** |
| S2 | `loadDiff` 未复用 `versionCount` 参数 | 低 | ❌ 未修复 |
| S3 | diff 响应双倍数据（raw + html） | 低 | ❌ 未修复 |
| S4 | 空 diff 时空白面板 | 低 | ❌ 未修复 |

### F1：`script.js` XSS 逃逸（R1 高优先级 → 仍为高风险）

R1 分析的 `esc()` 在内联 onclick 中的 HTML 实体解码逃逸问题在 0de43a0 中未被处理。

**影响范围：** `script.js` 中 8 处 innerHTML-onclick 模式（R1 §3.1 表格）。

**修复建议（与 R1 一致，推荐方案 B）：** 将所有内联 onclick 替换为 `addEventListener` 或事件委托。
- 当前 `canonical_id` 由服务端生成（UUID / KZOCR-xxx），不含 `'`，理论利用难度高
- 但未来引入用户自定义 ID 或元数据影响 ID 生成时攻击面打开

---

## 3. `diff.py` 二次审查

### 3.1 上次覆盖过的问题（R1 结论维持）

| 问题 | R1 结论 | 维持 |
|------|---------|------|
| LCS 算法正确性 | 正确 | ✅ |
| XSS 安全性（HTML 转义） | 安全 | ✅ |
| `splitlines(keepends=True)` | 好 | ✅ |
| 字符串拼接 O(n²) | 可接受（n < 5k）| ✅ |

### 3.2 新发现的细微问题

#### M1：未使用的 `Generator` 导入（`diff.py` 第 13 行）

```python
from typing import Generator
```

`_lcs_diff` 返回 `list[dict]`，不是 generator。`Generator` 在此模块中未被引用。属于未使用导入，不影响运行。

**建议：** 删除此行。

#### M2：`\r\n` 行尾未归一化（`diff.py` 第 26–27 行）

```python
old_lines = old.splitlines(keepends=True)
new_lines = new.splitlines(keepends=True)
```

`splitlines(keepends=True)` 保留换行符完整：`"a\r\n"` 保持为 `"a\r\n"`，`"a\n"` 保持为 `"a\n"`。LCS 比较时 `"a\r\n" != "a\n"`，导致跨平台文档对比时产生噪声 diff。

**严重性：低** — 当前场景（kzocr 医疗文档输出）统一使用 `\n`，跨平台输入尚未出现。但若将来接受 Windows 端上传文档会触发。

**建议：** 在 `diff_lines` 中统一行尾后送入 LCS：

```python
old_lines = [l.rstrip("\r\n") + "\n" for l in old.splitlines()]
new_lines = [l.rstrip("\r\n") + "\n" for l in new.splitlines()]
```

或更简洁：在 `diff_lines` 入口先做 `old.replace("\r\n", "\n")`。

---

## 4. 综合评分与优先级

| 编号 | 问题 | 严重性 | 优先级 | 位置 |
|------|------|--------|--------|------|
| F1 | `script.js` onclick XSS 逃逸（R1 未修） | 高（理论）/ 低（实际） | **高** — R1 已标记为高，应尽快修 | `script.js` |
| M1 | 未使用 `Generator` 导入 | 低 | 低 | `diff.py:13` |
| M2 | `\r\n` 行尾未归一化 | 低 | 低 | `diff.py:26` |
| — | 内容 split/join 归一化副作用 | 信息性 | 无需操作 | `api.py:211-216` |
| — | 负面检查可简化为 `v1 <= 0 or v2 <= 0` | 信息性 | 无需操作 | `api.py:204` |

**高优先级行动项：** 修复 `script.js` 中 R1 报告的 8 处 onclick XSS 逃逸。

---

## 5. 结论

0de43a0 中针对 `api.py` 的两项修复（5000 行上限 + 负数版本拒绝）在功能上完全正确：

- **5000 行上限** 有效防止 O(mn) DP 表耗尽内存。`splitlines()` + `"\n".join()` 的内容归一化有轻微副作用但不会影响 diff 正确性，可接受。
- **负数拒绝** 准确拦截了 `v1 < 0` 的输入。写法略有冗余但功能正确。

`diff.py` 核心算法在行数受限后是安全的，无需修改。

**总计：2 项修复通过验证，1 项 R1 高优先问题（F1）待修复。**

---

*评审日期：2026-07-10*
*评审人：CodeBuddy Code（general-purpose-48）*
