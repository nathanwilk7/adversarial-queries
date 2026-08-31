SET join_collapse_limit = 1;
SELECT count(*)
FROM (((((((((title CROSS JOIN aka_title) CROSS JOIN cast_info) CROSS JOIN company_type) CROSS JOIN movie_companies) CROSS JOIN movie_info) CROSS JOIN movie_info_idx) CROSS JOIN movie_link) CROSS JOIN name) CROSS JOIN person_info) CROSS JOIN role_type
WHERE aka_title.season_nr = 1
  AND aka_title.movie_id = title.id
  AND cast_info.movie_id = title.id
  AND cast_info.person_id = name.id
  AND cast_info.role_id = role_type.id
  AND movie_companies.company_type_id = company_type.id
  AND movie_companies.movie_id = title.id
  AND movie_info.movie_id = title.id
  AND movie_info_idx.movie_id = title.id
  AND movie_link.linked_movie_id = title.id
  AND person_info.person_id = name.id;
