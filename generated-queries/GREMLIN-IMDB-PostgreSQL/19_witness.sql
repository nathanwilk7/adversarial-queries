SET join_collapse_limit = 1;
SELECT count(*)
FROM (((((((movie_companies CROSS JOIN (title CROSS JOIN complete_cast)) CROSS JOIN company_type) CROSS JOIN cast_info) CROSS JOIN aka_name) CROSS JOIN name) CROSS JOIN role_type) CROSS JOIN info_type) CROSS JOIN movie_info
WHERE company_type.kind = 'special effects companies'
  AND aka_name.person_id = name.id
  AND cast_info.movie_id = title.id
  AND cast_info.person_id = name.id
  AND cast_info.role_id = role_type.id
  AND complete_cast.movie_id = title.id
  AND movie_companies.company_type_id = company_type.id
  AND movie_companies.movie_id = title.id
  AND movie_info.info_type_id = info_type.id
  AND movie_info.movie_id = title.id;
