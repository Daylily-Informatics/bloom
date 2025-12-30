# Dewey File Manager (DRAFT IN PROG)
A system to manage intake, storage, query, retrieval of all files RCRF interacts with in the course of working with our patients. The system also _will_ provide common interfaces for working with and sharing files stored in the system. Also, _in honor of the [Dewey Decimal Classification System](https://en.wikipedia.org/wiki/Dewey_Decimal_Classification)_.

# Stream Of Consciousness
* Files, not data, not interpretation, not patients. But, there needs to be some awareness of the interacting objecsts beyond files.
* ...

# Requirements
* Same as [bloom core](./README.md).

## AWS Credentials
* You should have the necessary credentials to access the S3 bucket(s) dewey will need to use. These should be stored in a `~/.aws/credentials` file (which should at a minimum have `aws_access_key_id=` & `aws_secret_access_key=`), with matching `~/.aws/config` file (which should at a minimum have `region=` & `output=json`).

## At Least One S3 Bucket
* You should have at least one S3 bucket to use with dewey. You can create one using the AWS console or the AWS CLI. Using default settings is fine.
* Naming of the bucket is important.    
  * The prefix pattern for all buckets used by dewey is `^([\w-]+)(-)(\d+)$`, ie: `daylily-dewey-0`. Where `$1$2` is the shared prefix for dewey buckets, ie: `daylily-dewey-` and `$3` is just the integer following the final `-`. Dewey uses `$3` to place new files based on if the `euid` in relation to `$3`.  
    * *_this is just a suggestion, no code tries to find files by inferring anything regarding locations from the file name or path._* 
    * This is intended as a simple mechanism to allow rolling to a new S3 bucket when needed. [Learn more in the dewey docs](./dewey.md).
  * buckets should not be renamed w/out coordinating updating the database for all affected files.
* When creating the bucket, `enable versioning` and `enable object lock`.  Once the bucket is created, go to the `properties` tab, scroll down to the object lock section, clik `edit` and set the lock type to `Governance` with a default lock time to the desired duration (years ideally?).

### BLOOM_DEWEY_S3_BUCKET_PREFIX= In The .env File
The S3 prefix all of your buckets will share should be set in the `.env` file as `BLOOM_DEWEY_S3_BUCKET_PREFIX=a-prefix-for-your-s3-bucket`. [More on the .env file](./cognito.md).

# Design

# Use Cases & Worked Examples



