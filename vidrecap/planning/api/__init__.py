"""规划层对外窗口：其他层要"计划"一律从这里进。

本窗口只做转出（re-export），不写任何逻辑。
内部私有实现（例如段落对半拆的细节）不出现在这里，属于本层私事。
"""

from vidrecap.planning.corrections import plan_corrections
from vidrecap.planning.sentences import split_sentences
from vidrecap.planning.splits import plan_compression
from vidrecap.planning.windows import plan_windows

__all__ = ["plan_compression", "plan_corrections", "plan_windows", "split_sentences"]
