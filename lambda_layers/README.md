# Creating a Custom AWS Lambda Layer for Python Packages

This guide explains how to install Python packages into a specific directory and package them into a ZIP file for use as a custom AWS Lambda layer. We'll use the `anthropic` package as an example.

## Prerequisites

- Python 3 installed (preferably Python 3.7 or higher)
- `pip` installed
- A terminal or command prompt

## Steps to Create a Custom Layer

### 1. Install the Package into a Target Directory
Use the `-t` or `--target` option with `pip` to specify the target directory for the package installation. AWS Lambda layers require Python packages to be in a specific directory structure, with all libraries located in the `python` subdirectory.

```bash
pip3 install anthropic -t anthropic/python/
```

### 2. Navigate to the Target Directory
Change into the base directory where the `python` folder is located. This is the directory you will package.

```bash
cd anthropic/
```

### 3. Create a ZIP Archive
Compress the `python` directory into a ZIP file. This ZIP file will be uploaded as the Lambda layer.

```bash
zip -r python_anthropic_layer.zip python
```

### 4. Upload the Layer to AWS Lambda
1. Go to the [AWS Lambda Console](https://console.aws.amazon.com/lambda/).
2. Click on **Layers** in the navigation pane.
3. Click **Create layer**.
4. Provide a name for your layer.
5. Upload the `python_anthropic_layer.zip` file.
6. Choose the compatible runtime (e.g., Python 3.8).
7. Click **Create**.

### 5. Add the Layer to a Lambda Function
1. Navigate to your Lambda function in the AWS Lambda Console.
2. In the **Layers** section, click **Add a layer**.
3. Choose **Custom layers**.
4. Select your layer from the list and specify the version.
5. Click **Add**.

## Notes
- Ensure the `python` directory structure is correct, as AWS Lambda requires packages to be in `python/lib/pythonX.X/site-packages` for compatibility.
- You can repeat these steps for any Python package by replacing `anthropic` with the desired package name.

## Example Structure
After following the steps, your directory structure should look like this before zipping:

```
anthropic/
├── python/
    ├── <package files and dependencies>
```

The resulting ZIP file will contain:

```
python_anthropic_layer.zip
├── python/
    ├── <package files and dependencies>
```

This ensures compatibility with AWS Lambda layers.

