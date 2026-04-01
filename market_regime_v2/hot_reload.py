"""
V2模型热加载模块
监控模型文件变化，自动重新加载
"""
import os
import time
import threading
from datetime import datetime
from pathlib import Path
import logging

logger = logging.getLogger(__name__)


class ModelHotReloader:
    """
    模型热加载器
    
    使用方式:
        reloader = ModelHotReloader(detector, model_path)
        reloader.start()  # 启动监控线程
        
        # 在主循环中检查
        if reloader.should_reload():
            reloader.reload()
    """
    
    def __init__(self, detector, model_path: str, check_interval: int = 60):
        """
        Args:
            detector: MarketRegimeDetectorV2 实例
            model_path: 模型文件路径
            check_interval: 检查间隔（秒）
        """
        self.detector = detector
        self.model_path = model_path
        self.check_interval = check_interval
        self.last_modified = 0
        self.last_checked = 0
        self._running = False
        self._thread = None
        
        # 初始化时记录当前修改时间
        self._update_timestamp()
    
    def _update_timestamp(self):
        """更新文件时间戳"""
        try:
            if os.path.exists(self.model_path):
                self.last_modified = os.path.getmtime(self.model_path)
        except Exception as e:
            logger.error(f"获取模型文件时间戳失败: {e}")
    
    def should_reload(self) -> bool:
        """检查是否需要重新加载"""
        try:
            if not os.path.exists(self.model_path):
                return False
            
            current_modified = os.path.getmtime(self.model_path)
            
            if current_modified > self.last_modified:
                # 检查文件是否写入完成（避免正在写入时加载）
                time.sleep(1)  # 等待1秒确保写入完成
                new_modified = os.path.getmtime(self.model_path)
                
                if new_modified == current_modified:  # 文件稳定
                    return True
        except Exception as e:
            logger.error(f"检查模型文件失败: {e}")
        
        return False
    
    def reload(self) -> bool:
        """重新加载模型"""
        try:
            logger.info("=" * 60)
            logger.info("🔄 检测到模型更新，开始热加载...")
            logger.info(f"   模型文件: {self.model_path}")
            logger.info(f"   修改时间: {datetime.fromtimestamp(os.path.getmtime(self.model_path))}")
            
            # 重新加载模型
            success = self.detector.load(self.model_path)
            
            if success:
                self._update_timestamp()
                logger.info("✅ 模型热加载成功！")
                logger.info("=" * 60)
                return True
            else:
                logger.error("❌ 模型热加载失败")
                return False
                
        except Exception as e:
            logger.error(f"热加载异常: {e}")
            return False
    
    def start_background_monitor(self):
        """启动后台监控线程"""
        if self._running:
            return
        
        self._running = True
        self._thread = threading.Thread(target=self._monitor_loop, daemon=True)
        self._thread.start()
        logger.info(f"🔄 模型热加载监控已启动（检查间隔: {self.check_interval}秒）")
    
    def stop(self):
        """停止监控"""
        self._running = False
        if self._thread:
            self._thread.join(timeout=5)
    
    def _monitor_loop(self):
        """后台监控循环"""
        while self._running:
            try:
                if self.should_reload():
                    self.reload()
                time.sleep(self.check_interval)
            except Exception as e:
                logger.error(f"监控循环异常: {e}")
                time.sleep(self.check_interval)


# 便捷函数
def setup_hot_reload(detector, model_path: str, background: bool = True):
    """
    快速设置热加载
    
    Args:
        detector: MarketRegimeDetectorV2 实例
        model_path: 模型文件路径
        background: 是否启动后台监控线程
        
    Returns:
        ModelHotReloader 实例
    """
    reloader = ModelHotReloader(detector, model_path)
    
    if background:
        reloader.start_background_monitor()
    
    return reloader
