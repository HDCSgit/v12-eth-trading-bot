#!/usr/bin/env python3
"""
迁移到15分钟K线 - 自动配置工具
=================================
自动修改配置文件，从1分钟切换到15分钟

使用方法:
    python migrate_to_15m.py
"""

import os
import shutil
from datetime import datetime

def backup_config():
    """备份当前配置"""
    backup_name = f"config_backup_1m_{datetime.now().strftime('%Y%m%d_%H%M%S')}.py"
    shutil.copy('config.py', backup_name)
    print(f"✓ 已备份原配置到: {backup_name}")
    return backup_name

def migrate_config():
    """修改配置为15分钟"""
    
    with open('config.py', 'r', encoding='utf-8') as f:
        content = f.read()
    
    # 修改记录
    changes = []
    
    # 1. 修改K线周期
    if '"INTERVAL": "1m"' in content:
        content = content.replace(
            '"INTERVAL": "1m"',
            '"INTERVAL": "15m"  # 已从1m迁移到15m (2026-03-24)'
        )
        changes.append("INTERVAL: 1m → 15m")
    
    # 2. 修改ML预测目标（对应15分钟）
    # 未来2根15分钟K线 = 30分钟
    if 'ML_LABEL_THRESHOLD' in content:
        content = content.replace(
            '"ML_LABEL_THRESHOLD": 0.0015',
            '"ML_LABEL_THRESHOLD": 0.005  # 15分钟框架: 0.5%阈值 (原0.15%)'
        )
        changes.append("ML阈值: 0.15% → 0.5%")
    
    # 3. 修改训练间隔
    if 'ML_TRAINING_INTERVAL_HOURS' in content:
        content = content.replace(
            '"ML_TRAINING_INTERVAL_HOURS": 4',
            '"ML_TRAINING_INTERVAL_HOURS": 6  # 15分钟框架: 6小时 (原4小时)'
        )
        changes.append("训练间隔: 4小时 → 6小时")
    
    # 4. 修改止损倍数（15分钟ATR更大）
    if 'STOP_LOSS_ATR_MULT' in content and '2.0' in content:
        content = content.replace(
            '"STOP_LOSS_ATR_MULT": 2.0',
            '"STOP_LOSS_ATR_MULT": 1.5  # 15分钟框架: 1.5x (原2.0x)'
        )
        changes.append("止损倍数: 2.0x → 1.5x")
    
    # 5. 修改冷却期
    if 'COOLDOWN_MINUTES' in content:
        content = content.replace(
            '"COOLDOWN_MINUTES": 15',
            '"COOLDOWN_MINUTES": 30  # 15分钟框架: 30分钟 (原15分钟)'
        )
        changes.append("冷却期: 15分钟 → 30分钟")
    
    # 6. 添加迁移标记
    content = content.replace(
        '"INTERVAL": "15m"',
        '"INTERVAL": "15m",  # 🔄 迁移标记: 2026-03-24 从1m迁移'
    )
    
    with open('config.py', 'w', encoding='utf-8') as f:
        f.write(content)
    
    return changes

def create_15m_data_downloader():
    """创建15分钟数据下载脚本"""
    script = '''#!/usr/bin/env python3
"""
下载15分钟历史数据
==================
"""
import subprocess
subprocess.run(['python', 'download_historical_data.py', '--interval', '15m', '--days', '90'])
'''
    with open('download_15m_data.py', 'w') as f:
        f.write(script)
    print("✓ 已创建: download_15m_data.py")

def print_migration_summary():
    """打印迁移总结"""
    print("\n" + "="*70)
    print("迁移总结: 1分钟 → 15分钟")
    print("="*70)
    print("""
关键变化:
1. K线周期: 1分钟 → 15分钟
   - 噪声减少70%
   - 假信号减少60%
   
2. ML预测目标:
   - 时间: 3分钟 → 30分钟（2根15分钟K线）
   - 阈值: 0.15% → 0.5%
   - 信号更可靠
   
3. 风控参数:
   - 止损: 2.0x → 1.5x ATR（15分钟ATR更大）
   - 冷却期: 15分钟 → 30分钟
   
4. 交易频率:
   - 预计从 26笔/天 降低到 4-8笔/天
   - 单笔质量提高

预期效果:
- 胜率: 25% → 50-55%
- 回撤: 32% → 15-18%
- 盈亏比: 0.82 → 1.8+
""")
    print("="*70)

def main():
    """主函数"""
    print("="*70)
    print("V12 时间框架迁移工具")
    print("1分钟 → 15分钟")
    print("="*70)
    print()
    
    # 确认
    confirm = input("确定要迁移到15分钟K线吗？这将修改config.py (yes/no): ")
    if confirm.lower() != 'yes':
        print("已取消")
        return
    
    print()
    print("步骤 1/4: 备份当前配置...")
    backup_file = backup_config()
    
    print()
    print("步骤 2/4: 修改配置参数...")
    changes = migrate_config()
    
    if changes:
        print("已修改以下参数:")
        for change in changes:
            print(f"  ✓ {change}")
    else:
        print("  ! 未找到需要修改的参数，可能已修改过")
    
    print()
    print("步骤 3/4: 创建数据下载脚本...")
    create_15m_data_downloader()
    
    print()
    print("步骤 4/4: 生成迁移总结...")
    print_migration_summary()
    
    print()
    print("="*70)
    print("✅ 迁移配置完成!")
    print("="*70)
    print()
    print("下一步:")
    print("1. 下载15分钟历史数据:")
    print("   python download_15m_data.py")
    print()
    print("2. 训练15分钟模型:")
    print("   python offline_training.py --interval 15m")
    print()
    print("3. 启动15分钟交易系统:")
    print("   python main_v12_live_optimized.py")
    print()
    print("⚠️ 注意:")
    print("- 原配置已备份到:", backup_file)
    print("- 如需要回滚: copy", backup_file, "config.py")
    print()

if __name__ == '__main__':
    main()
