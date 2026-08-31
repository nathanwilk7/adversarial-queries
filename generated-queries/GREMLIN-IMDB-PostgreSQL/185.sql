SELECT count(*)
FROM cast_info, company_name, info_type, kind_type, link_type, movie_companies, movie_info, movie_link, role_type, title
WHERE info_type.info = 'LD production country'
  AND kind_type.kind = 'movie'
  AND cast_info.movie_id = title.id
  AND cast_info.role_id = role_type.id
  AND movie_companies.company_id = company_name.id
  AND movie_companies.movie_id = title.id
  AND movie_info.info_type_id = info_type.id
  AND movie_info.movie_id = title.id
  AND movie_link.link_type_id = link_type.id
  AND movie_link.linked_movie_id = title.id
  AND title.kind_id = kind_type.id;
