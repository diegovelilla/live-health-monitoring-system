import os

def require_env(name: str) -> str:
    """
    Helper function to read required environment variables.
    
    Args:
        name (str): The name of the environment variable to read.
    
    Returns:
        str: The value of the environment variable.
    
    Raises:
        ValueError: If the environment variable is not set.
    """
    value = os.getenv(name)
    if not value:
        raise ValueError(f"Missing required environment variable: {name}")
    return value