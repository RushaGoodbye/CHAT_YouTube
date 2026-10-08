# RG YouTube Control 0.7.5 - pre-update backup reliability

- Prevent recursive copytree when recovery backups live under the application data directory.
- Exclude update-backups from data snapshots and avoid copying symlink loops.
- Verify that each recovery ZIP can be read and includes the database and manifest.
- Add regression tests for normal and deeply nested backup destinations.
- Keep existing 0.7.4 SEO stabilization unchanged.

Important for users updating from 0.7.3: if the existing program displays "maximum recursion depth exceeded" when it tries to create a backup, cancel that dialog. Close the program, make an independent backup of the data directory excluding the update-backups subfolder, then run the new standalone installer directly. The updated application will create subsequent backups without this recursion.
