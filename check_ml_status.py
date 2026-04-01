#!/usr/bin/env python3
"""Check ML model and feedback status"""
import os
import sqlite3
import pickle
from datetime import datetime

print("=" * 70)
print("ML System Status Check")
print("=" * 70)

# 1. 检查模型文件
model_path = 'ml_model_trained.pkl'
if os.path.exists(model_path):
    stat = os.stat(model_path)
    size_mb = stat.st_size / (1024 * 1024)
    mtime_str = datetime.fromtimestamp(stat.st_mtime).strftime('%Y-%m-%d %H:%M:%S')
    print(f"\n[Model File]")
    print(f"  Path: {model_path}")
    print(f"  Size: {size_mb:.2f} MB")
    print(f"  Last modified: {mtime_str}")
    
    # 加载模型信息
    try:
        with open(model_path, 'rb') as f:
            model = pickle.load(f)
        print(f"  Type: {type(model).__name__}")
    except Exception as e:
        print(f"  Load error: {e}")
else:
    print("\n[Model File] NOT FOUND!")

# 2. 检查反馈数据库
print(f"\n[ML Feedback Database]")
try:
    conn = sqlite3.connect('v12_optimized.db')
    c = conn.cursor()
    
    c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='ml_feedback'")
    if not c.fetchone():
        print("  ml_feedback table not found")
    else:
        c.execute('SELECT COUNT(*) FROM ml_feedback')
        total = c.fetchone()[0]
        print(f"  Total records: {total}")
        
        if total > 0:
            c.execute('SELECT COUNT(*) FROM ml_feedback WHERE evaluated=1')
            evaluated = c.fetchone()[0]
            print(f"  Evaluated: {evaluated}")
            
            c.execute('SELECT COUNT(*) FROM ml_feedback WHERE evaluated=1 AND was_correct=1')
            correct = c.fetchone()[0]
            if evaluated > 0:
                accuracy = correct / evaluated * 100
                print(f"  Accuracy: {correct}/{evaluated} = {accuracy:.1f}%")
            
            print("\n  Recent predictions:")
            c.execute('''
                SELECT timestamp, ml_regime, tech_regime, was_correct, actual_outcome 
                FROM ml_feedback 
                ORDER BY timestamp DESC LIMIT 5
            ''')
            for row in c.fetchall():
                status = "CORRECT" if row[3] == 1 else "WRONG" if row[3] == 0 else "PENDING"
                print(f"    {row[0]} | ML:{row[1]:12} | Tech:{row[2]:12} | {status}")
    
    conn.close()
except Exception as e:
    print(f"  Error: {e}")

# 3. 检查是否需要重新训练
print(f"\n[Recommendation]")
model_age_hours = (datetime.now() - datetime.fromtimestamp(os.stat(model_path).st_mtime)).total_seconds() / 3600
if model_age_hours < 24:
    print(f"  Model is fresh ({model_age_hours:.1f} hours old)")
    print(f"  => No need to retrain immediately")
else:
    print(f"  Model is {model_age_hours:.1f} hours old")
    print(f"  => Consider retraining if accuracy is low")

print("=" * 70)
