# 奶蛙表情包（已抠图）

共 **18** 张，全部为 768×768 透明背景 PNG，画面里只有奶蛙角色本身，没有底图、水印或文字。

## 文件说明

| 文件 | 说明 |
| --- | --- |
| `NN_*.png` | 抠图成品，RGBA，透明底 |
| `preview.png` | 全部表情的预览拼图（棋盘格底，可直观看透明区域） |
| `manifest.json` | 每张图的标题、原始出处、作者、授权、抠图参数 |

## 清单

| # | 文件 | 表情 | 原始出处 |
| --- | --- | --- | --- |
| 1 | `01_3_001_pengfu-daxiao.png` | 奶蛙捧腹大笑 | [原图](https://xn--yusy1ctb971x.cn/assets/reference/fullhd-nailong-01.jpg) |
| 2 | `02_3_005_chensi.png` | 沉思的奶蛙 | [原图](https://xn--yusy1ctb971x.cn/assets/reference/f-03.webp) |
| 3 | `03_3_008_zhenjing.png` | 震惊的奶蛙 | [原图](https://xn--yusy1ctb971x.cn/assets/reference/f-06.webp) |
| 4 | `04_3_002_fenchi-pengfu.png` | 粉色换色版捧腹大笑 | [原图](https://xn--yusy1ctb971x.cn/assets/reference/fullhd-nailong-02.jpg) |
| 5 | `05_3_006_sikao.png` | 思考的奶蛙 | [原图](https://xn--yusy1ctb971x.cn/assets/reference/f-04.webp) |
| 6 | `06_3_007_daxiao-zhiqian.png` | 大笑指前的奶蛙 | [原图](https://xn--yusy1ctb971x.cn/assets/reference/f-05.webp) |
| 7 | `07_3_010_baotou-daxiao.png` | 抱头大笑的奶蛙 | [原图](https://xn--yusy1ctb971x.cn/assets/reference/f-08.webp) |
| 8 | `08_3_013_lizheng.png` | 立正亮相·奶蛙 | [原图](https://xn--yusy1ctb971x.cn/assets/reference/f-09.webp) |
| 9 | `09_3_019_miyan-daxiao.png` | 眯眼大笑 | [原图](https://xn--yusy1ctb971x.cn/assets/reference/f-24.webp) |
| 10 | `10_3_020_wufu-daxiao.png` | 捂腹大笑 | [原图](https://xn--yusy1ctb971x.cn/assets/reference/f-25.webp) |
| 11 | `11_3_021_yangtian-daxiao.png` | 仰天大笑 | [原图](https://xn--yusy1ctb971x.cn/assets/reference/f-26.webp) |
| 12 | `12_5_012_anfu-daxiao.png` | 按腹大笑 | [原图](https://xn--yusy1ctb971x.cn/assets/reference/e-25.webp) |
| 13 | `13_5_015_pengxin-daxiao.png` | 捧心狂笑·动态 | [原图](https://xn--yusy1ctb971x.cn/assets/reference/e-22.gif) |
| 14 | `14_5_004_tuosai.png` | 托腮思考 | [原图](https://xn--yusy1ctb971x.cn/assets/reference/e-04.webp) |
| 15 | `15_8_028_weiyun.png` | 微愠奶蛙 | [原图](https://xn--yusy1ctb971x.cn/assets/reference/l-28.webp) |
| 16 | `16_8_029_qigugu.png` | 气鼓鼓奶蛙 | [原图](https://xn--yusy1ctb971x.cn/assets/reference/l-29.webp) |
| 17 | `17_8_023_tushe-bixin.png` | 吐舌比心奶蛙 | [原图](https://xn--yusy1ctb971x.cn/assets/reference/l-23.webp) |
| 18 | `18_8_019_queque.png` | 雀跃奶蛙 | [原图](https://xn--yusy1ctb971x.cn/assets/reference/l-19.webp) |

## 来源与授权

- 素材来自 [奶蛙宇宙](https://xn--yusy1ctb971x.cn/memes.html)（非官方爱好者站）收录的奶蛙表情包，单张原始出处见 `manifest.json` 中的 `source` 字段。
- 原站标注授权为「源仓库 MIT；角色权利归原权利人」，本项目仅作内部图像处理测试用图，请勿商用或二次分发。

## 抠图做法

1. 从画面边框估计背景色（区分白棚拍、灰棚拍、绿幕三种源）；
2. 以该颜色为基准，从边框做连通泛洪，得到"背景可达区域"，其余即角色主体；
3. 用颜色距离生成半透明软边（抗锯齿），绿幕图额外做绿色溢色抑制；
4. 0.7px 高斯羽化，裁到内容外接框，居中放入 768×768 透明画布。

对应脚本：`_tools/make_cutouts.py`（`selection.json` 为选图清单）。