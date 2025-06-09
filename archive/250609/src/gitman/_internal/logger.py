import os
import logging
import inspect
from logging.handlers import RotatingFileHandler

# Import logdir:
from ..config import LOGDIR

logdir = LOGDIR


class CustomAdapter(logging.LoggerAdapter):
    def process(self, msg, kwargs):
        # Get the stack frame 2 levels up (caller of the logging method)
        frame = inspect.currentframe()
        # Go up several frames to get past the adapter and logger internals
        try:
            # Move up to the actual calling frame (may need adjustment based on your call stack)
            for _ in range(3):  # Skip our adapter frames
                if frame.f_back:
                    frame = frame.f_back

            # Get info about the frame
            frameinfo = inspect.getframeinfo(frame)
            module = (
                frameinfo.filename.split("/")[-1].split("\\")[-1].replace(".py", "")
            )
            line = frameinfo.lineno
            function = frameinfo.function

            # Try to get class name if this is a method call
            try:
                if "self" in frame.f_locals:
                    class_name = frame.f_locals["self"].__class__.__name__
                    function = f"{class_name}.{function}"
            except Exception:
                pass  # Just use function name if we can't get class
            module_info = f"{module:^15}"
            # Format the log message with caller info
            extra_info = f"{module_info}| {function:^35} | {line:3}"
            return f"{extra_info} | {msg}", kwargs
        finally:
            # Clean up to avoid reference cycles
            del frame


# get_logger function
def get_logger(name, stream=False):
    logger = logging.getLogger(name)
    logger.setLevel(logging.DEBUG)

    # Prevent adding handlers multiple times
    if logger.handlers:
        return CustomAdapter(logger, {})

    # Create logs directory if it doesn't exist
    if not os.path.exists(logdir):
        os.makedirs(logdir)

    # Create file handler
    file_handler = RotatingFileHandler(
        f"{logdir}/{name}.log",
        maxBytes=1024 * 1024 * 10,  # 10MB
        backupCount=5,
    )
    file_handler.setLevel(logging.DEBUG)

    ## Create formatter and add it to the handlers
    # levelname = f"{levelname:^6}"
    formatter = logging.Formatter(
        "%(asctime)s - %(name)s - %(levelname)6s | %(message)s"
    )
    # formatter = logging.Formatter(
    #    "%(asctime)s - %(name)s - %(levelname)s - [%(module)s.%(funcName)s:%(lineno)d] - %(message)s"
    # )

    # Create console handler
    if stream:
        console_handler = logging.StreamHandler()
        console_handler.setLevel(logging.INFO)
        console_handler.setFormatter(formatter)
        logger.addHandler(console_handler)

    file_handler.setFormatter(formatter)

    # Add the handlers to the logger
    logger.addHandler(file_handler)

    # Wrap with our adapter
    adapted_logger = CustomAdapter(logger, {})

    for i in range(2):
        adapted_logger.info("")
    adapted_logger.info(
        f"\n\n\n\n\n**************** {name} Logger initialized ****************\n\n\n\n"
    )
    adapted_logger.info("")
    return adapted_logger  # LoggerWithContext(logger)


class LoggerWithContext:
    """Wrapper around logger to add context information about caller"""

    def __init__(self, logger):
        self.logger = logger

    def _get_caller_info(self):
        """Get the class and function name of the caller"""
        # Go back 2 frames to get the caller of the log method
        frame = inspect.currentframe()  # .f_back.f_back.f_back
        info = inspect.getframeinfo(frame)

        # Try to get the class name if called from a class method
        try:
            self_arg = frame.f_locals.get("self")
            if self_arg:
                class_name = self_arg.__class__.__name__
                return f"{class_name}.{info.function}"
            else:
                return info.function
        except Exception:
            # Fallback to just the function name if we can't get class info
            return info.function
        finally:
            # Clean up the frame reference to avoid reference cycles
            del frame

    def debug(self, msg, *args, **kwargs):
        self.logger.debug(msg, *args, **kwargs)

    def info(self, msg, *args, **kwargs):
        self.logger.info(msg, *args, **kwargs)

    def warning(self, msg, *args, **kwargs):
        self.logger.warning(msg, *args, **kwargs)

    def error(self, msg, *args, **kwargs):
        self.logger.error(msg, *args, **kwargs)

    def critical(self, msg, *args, **kwargs):
        self.logger.critical(msg, *args, **kwargs)

    def exception(self, msg, *args, exc_info=True, **kwargs):
        self.logger.exception(msg, *args, exc_info=exc_info, **kwargs)


logger = get_logger("gitman_Main")
