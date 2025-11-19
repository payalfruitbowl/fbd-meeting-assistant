# Fireflies Transcript Processor

FastAPI server to fetch, process, and generate Word documents from Fireflies transcripts.

## Features

- Fetches transcripts from Fireflies API for the past week
- Filters transcripts by unique clients
- Formats conversations into readable text
- Generates Word (.docx) documents for each client
- Dockerized for easy deployment

## Project Structure

```
fruitbowl/
├── app/
│   ├── __init__.py
│   ├── main.py              # FastAPI application and endpoints
│   ├── config.py            # Configuration settings
│   └── services/
│       ├── __init__.py
│       ├── fireflies_client.py    # Fireflies API client
│       ├── data_processor.py     # Data filtering and formatting
│       └── word_generator.py      # Word document generation
├── output/                  # Generated Word documents (created automatically)
├── requirements.txt
├── Dockerfile
├── docker-compose.yml
├── .env.example
└── README.md
```

## Setup

1. **Clone the repository and navigate to the project directory**

2. **Create a `.env` file** from the example:
   ```bash
   cp .env.example .env
   ```

3. **Update `.env` with your Fireflies API key:**
   ```
   FIREFLIES_API_KEY=your_actual_api_key_here
   ```

## Running with Docker

1. **Build and run with Docker Compose:**
   ```bash
   docker-compose up --build
   ```

2. **The API will be available at:** `http://localhost:8000`

## Running Locally

1. **Create a virtual environment:**
   ```bash
   python -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   ```

2. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

3. **Run the server:**
   ```bash
   uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
   ```

## API Endpoints

### Health Check
- `GET /` - Root endpoint
- `GET /health` - Health check endpoint

### Process Transcripts
- `POST /process-transcripts` - Main endpoint to process weekly transcripts
  - Fetches transcripts from Fireflies API for the past week
  - Filters by unique clients
  - Generates Word documents for each client
  - Returns list of generated files

## Next Steps

Once you provide the Fireflies API documentation, we'll update:
- `app/services/fireflies_client.py` - API endpoint and parameters
- `app/services/data_processor.py` - Data extraction logic based on actual response structure

## Output

Generated Word documents will be saved in the `output/` directory with the format:
`{client_name}_{timestamp}.docx`


