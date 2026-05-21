terraform {
  required_version = ">= 1.0"
  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 5.0"
    }
  }
}

provider "google" {
  project = "your-gcp-project-id"
  region  = "us-central1"
}

resource "google_storage_bucket" "public_data" {
  name          = "my-org-public-data-1234"
  location      = "US"
  storage_class = "STANDARD"

  labels = {
    name = "Public data bucket"
  }
}

resource "google_storage_bucket_iam_member" "public_data_all_users" {
  bucket = google_storage_bucket.public_data.name
  role   = "roles/storage.objectViewer"
  member = "allUsers"
}

resource "google_service_account" "function_sa" {
  account_id   = "function-execution-sa"
  display_name = "Cloud Function Execution Service Account"
}

resource "google_project_iam_member" "function_admin" {
  project = "your-gcp-project-id"
  role    = "roles/owner"
  member  = "serviceAccount:${google_service_account.function_sa.email}"
}

resource "google_storage_bucket" "app_logs" {
  name          = "my-org-app-logs"
  location      = "US"
  storage_class = "STANDARD"

  labels = {
    name        = "Application logs"
    environment = "production"
    owner       = "platform-team"
  }
}

resource "google_firestore_database" "users_db" {
  project     = "your-gcp-project-id"
  name        = "users-database"
  location_id = "nam5"
  type        = "FIRESTORE_NATIVE"
}

resource "google_compute_network" "default" {
  name                    = "default-network"
  auto_create_subnetworks = true
}

resource "google_compute_router" "main" {
  name    = "main-router"
  region  = "us-central1"
  network = google_compute_network.default.id
}

resource "google_compute_router_nat" "main" {
  name   = "main-nat"
  router = google_compute_router.main.name
  region = "us-central1"

  source_subnetwork_ip_ranges_to_nat = "ALL_SUBNETWORKS_ALL_IP_RANGES"
  nat_ip_allocate_option             = "AUTO_ONLY"
}

resource "google_compute_instance" "bastion" {
  name         = "bastion-host"
  machine_type = "e2-medium"
  zone         = "us-central1-a"

  boot_disk {
    initialize_params {
      image = "debian-cloud/debian-11"
    }
  }

  network_interface {
    network = google_compute_network.default.name
  }
}
