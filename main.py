import functions_framework
from pipeline.run_pipeline import run_pipeline

@functions_framework.http
def main(request):
    """HTTP Cloud Function entry point."""
    run_pipeline()
    return "Pipeline completed successfully", 200
