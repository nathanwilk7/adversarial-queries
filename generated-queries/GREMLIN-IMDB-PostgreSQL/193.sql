SELECT count(*)
FROM cast_info, company_name, movie_companies, movie_info_idx, movie_link, name, role_type, title
WHERE name.imdb_index = ''
  AND cast_info.movie_id = title.id
  AND cast_info.person_id = name.id
  AND cast_info.role_id = role_type.id
  AND movie_companies.company_id = company_name.id
  AND movie_companies.movie_id = title.id
  AND movie_info_idx.movie_id = title.id
  AND movie_link.linked_movie_id = title.id;
