
from b2sdk.v2 import InMemoryAccountInfo, B2Api
from app.core.config import get_settings

class B2Service:
    """Service to interact with Backblaze B2 bucket."""
    def __init__(self):
        settings = get_settings()
        self.key_id = settings.KEY_ID
        self.application_key = settings.APPLICATION_KEY
        self.bucket_name = settings.BUCKET_NAME

        info = InMemoryAccountInfo()
        self.b2_api = B2Api(info)
        self.b2_api.authorize_account("production", self.key_id, self.application_key)

    def get_bucket(self):
        """
        Get the bucket by name.
        
        Returns:
            Bucket: Instancia del bucket.
        """
        
        return self.b2_api.get_bucket_by_name(self.bucket_name)

    def upload_file(self, local_file_path, file_name_in_bucket):
        """
            Upload a file to the bucket.
            
            Args:
                local_file_path (str): Path to the local file.
                file_name_in_bucket (str): Name of the file in the bucket.
            
            Returns:
                File: Instance of the uploaded file.
        """
        bucket = self.get_bucket()
        metadata = {"source": "osai-app"}
        
        uploaded_file = bucket.upload_local_file(
            local_file=local_file_path,
            file_name=file_name_in_bucket,
            file_infos=metadata
        )
        
        return uploaded_file

